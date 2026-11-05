"""Fresh-container Docker execution for untrusted Python candidates."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import struct
import time
import uuid

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound

from .contracts import ExecutionRequest, ExecutionResult


DEFAULT_IMAGE = "sandbox-agent-runtime:local"
MAX_OUTPUT_BYTES = 64 * 1024
MEMORY_BYTES = 256 * 1024 * 1024
CPU_PERIOD = 100_000
CPU_QUOTA = 100_000
PID_LIMIT = 32
_MARKER = b"\x1eSANDBOX_RESULT\x1e"
_TMPFS = {
    "/tmp": "rw,noexec,nosuid,nodev,size=16m",
    "/work": "rw,noexec,nosuid,nodev,size=16m,mode=1777",
}


class SandboxUnavailable(RuntimeError):
    """The local engine or prebuilt runtime cannot provide required controls."""


def _socket_candidates() -> list[Path]:
    candidates = [Path("/var/run/docker.sock")]
    home = Path.home()
    candidates.extend((home / ".docker/run/docker.sock", home / "Library/Containers/com.docker.docker/Data/docker.raw.sock"))
    if os.name == "posix" and sys_platform_linux():
        candidates.append(Path(f"/run/user/{os.getuid()}/docker.sock"))
    return candidates


def sys_platform_linux() -> bool:
    # Kept tiny and explicit so the runner never consults Docker contexts or
    # DOCKER_HOST, either of which could point at an unexpected remote daemon.
    return os.uname().sysname == "Linux"


def _docker_client(timeout: float = 5.0) -> docker.DockerClient:
    for path in _socket_candidates():
        client = None
        try:
            if not path.exists() or not path.is_socket():
                continue
            client = docker.DockerClient(base_url=f"unix://{path}", timeout=timeout, version="auto")
            client.ping()
            return client
        except DockerException:
            if client is not None:
                client.close()
    raise SandboxUnavailable("no responding local Docker Unix socket was found")


def _engine_preflight(client: docker.DockerClient) -> dict:
    info = client.info()
    if info.get("OSType") != "linux":
        raise SandboxUnavailable("the Docker engine must run Linux containers")
    if str(info.get("CgroupVersion", "")) != "2":
        raise SandboxUnavailable("the Docker engine must use cgroups v2")
    security = " ".join(info.get("SecurityOptions") or []).lower()
    if "seccomp" not in security:
        raise SandboxUnavailable("the Docker engine does not report seccomp support")
    return info


def _image_id(client: docker.DockerClient, image: str) -> str:
    try:
        runtime = client.images.get(image)
    except ImageNotFound as exc:
        raise SandboxUnavailable(
            f"runtime image {image!r} is not built; build it explicitly with `make sandbox-image`"
        ) from exc
    attrs = runtime.attrs
    if attrs.get("Os") != "linux" or attrs.get("Architecture") not in {"amd64", "arm64"}:
        raise SandboxUnavailable("runtime image must target Linux amd64 or arm64")
    return attrs["Id"]


def _verify_container_config(attrs: dict) -> None:
    config = attrs.get("Config") or {}
    host = attrs.get("HostConfig") or {}
    failures = []
    if config.get("User") != "65532:65532":
        failures.append("fixed non-root user")
    if host.get("ReadonlyRootfs") is not True:
        failures.append("read-only root filesystem")
    if host.get("NetworkMode") != "none":
        failures.append("disabled networking")
    if host.get("Memory") != MEMORY_BYTES or host.get("MemorySwap") != MEMORY_BYTES:
        failures.append("256 MiB memory and swap caps")
    if host.get("CpuQuota") != CPU_QUOTA or host.get("CpuPeriod") != CPU_PERIOD:
        failures.append("one-core CPU quota")
    if host.get("PidsLimit") != PID_LIMIT:
        failures.append("process limit")
    if "ALL" not in (host.get("CapDrop") or []):
        failures.append("dropped capabilities")
    if "no-new-privileges:true" not in (host.get("SecurityOpt") or []):
        failures.append("no-new-privileges")
    mounts = attrs.get("Mounts") or []
    tmpfs_mounts = {
        mount.get("Destination") for mount in mounts
        if mount.get("Type") == "tmpfs" and not mount.get("Source")
    }
    if host.get("Binds") or any(mount.get("Type") != "tmpfs" for mount in mounts):
        failures.append("absence of host mounts")
    if mounts and tmpfs_mounts != set(_TMPFS):
        failures.append("only the declared tmpfs mounts")
    if host.get("Devices") or host.get("DeviceRequests") or host.get("Privileged"):
        failures.append("absence of devices and privileged mode")
    configured_tmpfs = host.get("Tmpfs") or {}
    if set(configured_tmpfs) != set(_TMPFS) or any(
        set(str(configured_tmpfs.get(path, "")).split(",")) != set(options.split(","))
        for path, options in _TMPFS.items()
    ):
        failures.append("restricted tmpfs work areas")
    if host.get("CgroupnsMode") != "private":
        failures.append("private cgroup namespace")
    if failures:
        raise SandboxUnavailable("container configuration failed inspection: " + ", ".join(failures))


class _OutputLimitExceeded(ValueError):
    pass


def _frame_chunks(buffer: bytearray, total: int, limit: int):
    """Yield complete Docker multiplexed stdout/stderr frames in place."""
    while len(buffer) >= 8:
        stream = buffer[0]
        length = struct.unpack(">I", buffer[4:8])[0]
        if stream not in (1, 2):
            raise ValueError("invalid Docker attach stream frame")
        if total + length > limit:
            raise _OutputLimitExceeded
        if len(buffer) < 8 + length:
            return
        data = bytes(buffer[8:8 + length])
        del buffer[:8 + length]
        yield stream, data


def _read_attach(sock, payload: bytes, deadline: float, output_limit: int):
    """Send one request and collect bounded multiplexed output until EOF."""
    sock.setblocking(False)
    outgoing = memoryview(payload + b"\n")
    sent = 0
    pending = bytearray()
    stdout = bytearray()
    stderr = bytearray()
    total = 0
    output_limited = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return bytes(stdout), bytes(stderr), True, output_limited
        readers = [sock]
        writers = [sock] if sent < len(outgoing) else []
        readable, writable, exceptional = select.select(readers, writers, [sock], min(remaining, 0.1))
        if exceptional:
            raise OSError("Docker attach stream reported an error")
        if writable:
            try:
                count = sock.send(outgoing[sent:sent + 64 * 1024])
            except (BlockingIOError, InterruptedError):
                count = 0
            if count:
                sent += count
        if readable:
            try:
                chunk = sock.recv(16 * 1024)
            except (BlockingIOError, InterruptedError):
                continue
            if not chunk:
                return bytes(stdout), bytes(stderr), False, output_limited
            pending.extend(chunk)
            while len(pending) >= 8:
                try:
                    stream, data = next(_frame_chunks(pending, total, output_limit))
                except _OutputLimitExceeded:
                    output_limited = True
                    return bytes(stdout), bytes(stderr), False, output_limited
                except StopIteration:
                    break
                total += len(data)
                (stdout if stream == 1 else stderr).extend(data)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _parse_report(stderr: bytes) -> tuple[bytes, dict | None, str | None]:
    index = stderr.rfind(_MARKER)
    if index < 0:
        return stderr, None, "sandbox result marker is missing"
    output = stderr[:index]
    encoded = stderr[index + len(_MARKER):].splitlines()[0]
    try:
        report = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError):
        return output, None, "sandbox result marker is malformed"
    if not isinstance(report, dict):
        return output, None, "sandbox result must be a JSON object"
    if report.get("protocol_error"):
        details = report.get("details") or []
        suffix = "; ".join(str(item)[:256] for item in details[:8])
        message = str(report["protocol_error"])
        return output, report, f"{message}: {suffix}" if suffix else message
    return output, report, None


class DockerSandbox:
    """Executes one candidate in a newly created and removed local container."""

    def __init__(self, image: str = DEFAULT_IMAGE, output_limit: int = MAX_OUTPUT_BYTES):
        if output_limit != MAX_OUTPUT_BYTES:
            if isinstance(output_limit, bool) or not 1024 <= output_limit <= MAX_OUTPUT_BYTES:
                raise ValueError("output_limit must be between 1 KiB and 64 KiB")
        self.image = image
        self.output_limit = output_limit

    def doctor(self) -> dict:
        client = _docker_client()
        try:
            info = _engine_preflight(client)
            image_id = _image_id(client, self.image)
            result = {
                "engine_version": info.get("ServerVersion"),
                "operating_system": info.get("OperatingSystem"),
                "architecture": info.get("Architecture"),
                "cgroup_version": info.get("CgroupVersion"),
                "image": self.image,
                "image_id": image_id,
                "output_limit_bytes": self.output_limit,
            }
            try:
                ready, details = self._runtime_probe(client, image_id)
                result["ready"] = ready
                result["readiness_details"] = details
            except (APIError, DockerException, OSError, ValueError) as exc:
                result["ready"] = False
                result["readiness_details"] = [f"runtime probe failed: {str(exc)[:256]}"]
            return result
        finally:
            client.close()

    def _create_container(self, client, image_id: str, execution_id: str, *, stdin_open: bool,
                          command=None):
        return client.containers.create(
            image=image_id,
            command=command,
            stdin_open=stdin_open,
            tty=False,
            detach=True,
            user="65532:65532",
            read_only=True,
            network_mode="none",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            cgroupns="private",
            mem_limit=MEMORY_BYTES,
            memswap_limit=MEMORY_BYTES,
            cpu_period=CPU_PERIOD,
            cpu_quota=CPU_QUOTA,
            pids_limit=PID_LIMIT,
            tmpfs=_TMPFS,
            ulimits=[
                docker.types.Ulimit(name="nofile", soft=64, hard=64),
                docker.types.Ulimit(name="core", soft=0, hard=0),
            ],
            shm_size=1024 * 1024,
            labels={"sandbox-agent.project": "05-sandboxed-code-agent",
                    "sandbox-agent.execution": execution_id},
        )

    def _runtime_probe(self, client, image_id: str) -> tuple[bool, list[str]]:
        """Check effective in-container limits using only the trusted launcher."""
        container = None
        try:
            container = self._create_container(
                client, image_id, uuid.uuid4().hex, stdin_open=False, command=["--probe"]
            )
            _verify_container_config(client.api.inspect_container(container.id))
            container.start()
            state = container.wait(timeout=5)
            logs = client.api.logs(container.id, stdout=True, stderr=True, stream=False)
            if not isinstance(logs, bytes) or len(logs) > 16 * 1024:
                return False, ["trusted runtime probe returned oversized or invalid logs"]
            _, report, error = _parse_report(logs)
            if error:
                return False, [error]
            if report and report.get("ready") is True and state.get("StatusCode") == 0:
                return True, []
            details = report.get("details") if report else None
            return False, [str(item)[:256] for item in details or [
                f"trusted runtime probe exited {state.get('StatusCode')}"
            ]]
        finally:
            if container is not None:
                try:
                    client.api.remove_container(container.id, force=True, v=True)
                except (APIError, NotFound, DockerException):
                    pass

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        payload = request.to_payload()
        execution_id = uuid.uuid4().hex
        started = time.monotonic()
        container = None
        attach = None
        client = None
        timed_out = False
        output_limited = False
        stdout = b""
        stderr = b""
        exit_code = None
        oom_killed = False
        infra_error = None
        protocol_error = None
        report = None
        try:
            client = _docker_client(timeout=min(5.0, request.timeout_seconds))
            _engine_preflight(client)
            image_id = _image_id(client, self.image)
            container = self._create_container(client, image_id, execution_id, stdin_open=True)
            container_id = container.id
            attrs = client.api.inspect_container(container_id)
            _verify_container_config(attrs)
            client.api.start(container_id)
            attach = client.api.attach_socket(container_id, params={
                "stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": 1,
            })
            stdout, stderr, timed_out, output_limited = _read_attach(
                attach._sock, payload, time.monotonic() + request.timeout_seconds, self.output_limit
            )
            if not timed_out and not output_limited:
                try:
                    final = client.api.inspect_container(container_id)
                    final_state = final.get("State") or {}
                    exit_code = final_state.get("ExitCode")
                    oom_killed = bool(final_state.get("OOMKilled"))
                except (APIError, NotFound):
                    pass
                stderr, report, protocol_error = _parse_report(stderr)
        except (SandboxUnavailable, APIError, DockerException, OSError, ValueError) as exc:
            infra_error = str(exc)[:512]
        finally:
            if attach is not None:
                try:
                    attach.close()
                except OSError:
                    pass
            if container is not None and client is not None:
                try:
                    current = client.api.inspect_container(container.id)
                    if current.get("State", {}).get("Running"):
                        client.api.kill(container.id)
                except (APIError, NotFound, DockerException):
                    pass
                try:
                    client.api.remove_container(container.id, force=True, v=True)
                    container = None
                except (APIError, NotFound, DockerException) as exc:
                    infra_error = infra_error or f"container cleanup failed: {str(exc)[:256]}"
            if client is not None:
                client.close()

        if timed_out:
            protocol_error = None
            report = None
        elif output_limited:
            protocol_error = None
            report = None
        return ExecutionResult(
            execution_id=execution_id,
            exit_code=exit_code,
            stdout=_decode(stdout),
            stderr=_decode(stderr),
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
            output_limited=output_limited,
            oom_killed=oom_killed,
            infrastructure_error=infra_error or (
                protocol_error if report and report.get("ready") is False else None
            ),
            protocol_error=protocol_error,
            result_present=bool(report and report.get("result_present")),
            return_value=report.get("return_value") if report else None,
            exception_type=report.get("exception_type") if report else None,
            exception=report.get("exception") if report else None,
        )
