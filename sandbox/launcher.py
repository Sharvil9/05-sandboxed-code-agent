"""Trusted in-container launcher. Candidate code runs only in this container."""

import io
import json
import os
from pathlib import Path
import re
import sys
import traceback
import types

_MAX_INPUT_BYTES = 512 * 1024
_MAX_CODE_BYTES = 16 * 1024
_MAX_RESULT_BYTES = 8192
_MAX_FIXTURES = 4
_MAX_FIXTURE_BYTES = 64 * 1024
_MAX_FIXTURE_TOTAL = 128 * 1024
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MARKER = b"\x1eSANDBOX_RESULT\x1e"
_json_loads = json.loads
_json_dumps = json.dumps
_format_exception = traceback.format_exception
_original_stdout = sys.stdout
_original_stderr = sys.stderr


def _write_report(report):
    encoded = _json_dumps(report, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_RESULT_BYTES:
        encoded = _json_dumps({
            "result_present": False,
            "exception_type": "ObservationTooLarge",
            "exception": "candidate result exceeds the observation limit",
        }, separators=(",", ":")).encode("utf-8")
    _original_stderr.buffer.write(_MARKER + encoded + b"\n")
    _original_stderr.flush()


def _make_report_writer():
    output = _original_stderr.buffer
    dumps = _json_dumps
    marker = _MARKER
    result_limit = _MAX_RESULT_BYTES

    def write_report(report):
        encoded = dumps(report, ensure_ascii=False, allow_nan=False,
                        sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > result_limit:
            encoded = dumps({
                "result_present": False,
                "exception_type": "ObservationTooLarge",
                "exception": "candidate result exceeds the observation limit",
            }, separators=(",", ":")).encode("utf-8")
        output.write(marker + encoded + b"\n")
        output.flush()

    return write_report


def _preflight():
    failures = []
    try:
        if os.getuid() != 65532 or os.getgid() != 65532:
            failures.append("unexpected user identity")
        status = {}
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                status[key] = value.strip()
        if status.get("CapEff") != "0000000000000000":
            failures.append("effective capabilities are not empty")
        if status.get("NoNewPrivs") != "1":
            failures.append("no-new-privileges is not set")
        if status.get("Seccomp") != "2":
            failures.append("seccomp filter is not active")
        expected = {
            "memory.max": "268435456",
            "memory.swap.max": "0",
            "pids.max": "32",
        }
        for filename, wanted in expected.items():
            actual = Path("/sys/fs/cgroup", filename).read_text(encoding="ascii").strip()
            if actual != wanted:
                failures.append(f"{filename} is {actual!r}, expected {wanted!r}")
        cpu = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="ascii").split()
        if cpu != ["100000", "100000"]:
            failures.append(f"cpu.max is {' '.join(cpu)!r}, expected '100000 100000'")
    except (OSError, ValueError) as exc:
        failures.append(f"sandbox preflight failed ({type(exc).__name__})")
    return failures


def _validate_request(request):
    expected = {"code", "mode", "entrypoint", "arguments", "stdin", "script_args", "fixtures", "compile_only"}
    if not isinstance(request, dict) or set(request) != expected:
        raise ValueError("execution request fields do not match the protocol")
    code = request["code"]
    if not isinstance(code, str) or not code.strip() or len(code.encode("utf-8")) > _MAX_CODE_BYTES:
        raise ValueError("candidate source is empty or exceeds the code limit")
    if not isinstance(request["mode"], str) or request["mode"] not in {"function", "script"}:
        raise ValueError("unsupported execution mode")
    if not isinstance(request["entrypoint"], str) or not request["entrypoint"].isidentifier():
        raise ValueError("function entrypoint must be a Python identifier")
    if not isinstance(request["arguments"], list) or not isinstance(request["script_args"], list):
        raise ValueError("arguments and script_args must be arrays")
    if any(not isinstance(arg, str) or len(arg) > 1024 for arg in request["script_args"]):
        raise ValueError("script arguments must be short strings")
    if not isinstance(request["stdin"], str) or len(request["stdin"].encode("utf-8")) > 64 * 1024:
        raise ValueError("stdin exceeds the input limit")
    if type(request["compile_only"]) is not bool:
        raise ValueError("compile_only must be a boolean")
    fixtures = request["fixtures"]
    if not isinstance(fixtures, dict) or len(fixtures) > _MAX_FIXTURES:
        raise ValueError("fixtures must be an object with at most four files")
    total = 0
    for name, content in fixtures.items():
        if (not isinstance(name, str) or not _FILENAME.fullmatch(name) or
                name in {"solution.py", "request.json"} or "/" in name or "\\" in name):
            raise ValueError("fixture filenames must be safe, flat names")
        if not isinstance(content, str):
            raise ValueError("fixture contents must be UTF-8 text")
        size = len(content.encode("utf-8"))
        if size > _MAX_FIXTURE_BYTES:
            raise ValueError("a fixture exceeds the file size limit")
        total += size
    if total > _MAX_FIXTURE_TOTAL:
        raise ValueError("fixtures exceed the total size limit")
    try:
        _json_dumps(request["arguments"], allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("function arguments must be finite JSON data") from exc


def main():
    if sys.argv[1:] == ["--probe"]:
        failures = _preflight()
        _write_report({
            "ready": not failures,
            "protocol_error": None if not failures else "sandbox preflight failed",
            "details": failures,
        })
        return 0 if not failures else 125
    failures = _preflight()
    if failures:
        _write_report({"ready": False, "protocol_error": "sandbox preflight failed", "details": failures})
        return 125
    write_report = _make_report_writer()
    try:
        raw = sys.stdin.buffer.readline(_MAX_INPUT_BYTES + 2)
        if not raw.endswith(b"\n") or len(raw) > _MAX_INPUT_BYTES + 1:
            raise ValueError("request exceeds the protocol size limit")
        request = _json_loads(raw[:-1].decode("utf-8"))
        _validate_request(request)
        work = Path("/work")
        (work / "solution.py").write_text(request["code"], encoding="utf-8")
        for name, content in request["fixtures"].items():
            (work / name).write_text(content, encoding="utf-8")
        os.chdir(work)
        source = (work / "solution.py").read_text(encoding="utf-8")
        compiled = compile(source, "solution.py", "exec")
    except Exception as exc:
        write_report({
            "protocol_error": "invalid execution request",
            "exception_type": type(exc).__name__,
            "exception": str(exc)[:1024],
        })
        return 125

    module_name = "__main__" if request["mode"] == "script" else "solution"
    module = types.ModuleType(module_name)
    module.__file__ = str(work / "solution.py")
    module.__package__ = None
    sys.modules[module_name] = module
    sys.argv = ["solution.py", *request["script_args"]] if request["mode"] == "script" else ["solution.py"]
    sys.stdin = io.StringIO(request["stdin"])
    report = {"result_present": False}
    exit_code = 0
    try:
        exec(compiled, module.__dict__)
        if request["mode"] == "function":
            function = getattr(module, request["entrypoint"], None)
            if not callable(function):
                raise AttributeError(f"function {request['entrypoint']!r} is missing or not callable")
            if not request["compile_only"]:
                result = function(*request["arguments"])
                # Serialize before passing across the trust boundary; unsupported objects fail honestly.
                result_json = _json_dumps(result, ensure_ascii=False, allow_nan=False,
                                          sort_keys=True, separators=(",", ":"))
                if len(result_json.encode("utf-8")) > _MAX_RESULT_BYTES:
                    raise ValueError("candidate return value exceeds the result limit")
                report = {"result_present": True, "return_value": _json_loads(result_json)}
    except SystemExit as exc:
        if request["mode"] != "script" or exc.code not in (None, 0):
            exit_code = 1 if not isinstance(exc.code, int) or exc.code == 0 else int(exc.code)
            report = {"result_present": False, "exception_type": "SystemExit",
                      "exception": str(exc.code)[:1024]}
    except BaseException as exc:
        exit_code = 1
        try:
            stack = "".join(_format_exception(type(exc), exc, exc.__traceback__))[-8192:]
            _original_stderr.write(stack)
            _original_stderr.flush()
        except Exception:
            pass
        report = {
            "result_present": False,
            "exception_type": type(exc).__name__[:128],
            "exception": str(exc)[:1024],
        }
    try:
        write_report(report)
    except Exception:
        return 125
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
