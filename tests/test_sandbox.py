"""Real Docker boundary tests; no candidate code is imported by pytest."""

import os

import pytest

from sandbox_agent.contracts import ExecutionRequest
from sandbox_agent.sandbox import DockerSandbox, _docker_client


pytestmark = pytest.mark.sandbox


def _project_containers():
    client = _docker_client()
    try:
        return {
            item.id for item in client.containers.list(
                all=True, filters={"label": "sandbox-agent.project=05-sandboxed-code-agent"}
            )
        }
    finally:
        client.close()


@pytest.fixture(scope="module")
def sandbox():
    instance = DockerSandbox()
    status = instance.doctor()
    if not status["ready"]:
        pytest.skip("effective Docker resource limits are unavailable: " + "; ".join(status["readiness_details"]))
    return instance


def test_doctor_checks_effective_container_limits():
    before = _project_containers()
    status = DockerSandbox().doctor()
    assert status["engine_version"]
    assert status["cgroup_version"] == "2"
    assert isinstance(status["ready"], bool)
    assert isinstance(status["readiness_details"], list)
    if not status["ready"]:
        assert status["readiness_details"]
        if os.environ.get("SANDBOX_REQUIRE_READY") == "1":
            pytest.fail("Docker sandbox is not ready: " + "; ".join(status["readiness_details"]))

    assert _project_containers() == before


def test_runtime_preflight_blocks_candidates_when_limits_are_missing():
    instance = DockerSandbox()
    status = instance.doctor()
    if status["ready"]:
        pytest.skip("runtime is ready; positive isolation tests cover this engine")
    before = _project_containers()
    result = instance.execute(ExecutionRequest(
        code="def solve():\n    print('candidate-must-not-run')\n    return True\n"
    ))
    assert result.infrastructure_error is not None
    assert "sandbox preflight failed" in result.infrastructure_error
    assert result.exit_code == 125
    assert "candidate-must-not-run" not in result.stdout
    assert result.result_present is False
    assert _project_containers() == before


def test_function_runs_in_fresh_limited_container(sandbox):
    request = ExecutionRequest(
        code="def solve(value):\n    return {'value': value, 'ok': True}\n",
        arguments=[7],
    )
    payload = request.to_payload()
    assert b"expected" not in payload and b"tests" not in payload

    result = sandbox.execute(request)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.result_present is True
    assert result.return_value == {"ok": True, "value": 7}
    assert result.timed_out is False


def test_candidate_cannot_replace_the_trusted_report_function(sandbox):
    code = (
        "import sys\n"
        "def solve():\n"
        "    launcher = sys.modules['__main__']\n"
        "    launcher._write_report = lambda report: None\n"
        "    return 'actual result'\n"
    )
    result = sandbox.execute(ExecutionRequest(code=code))
    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.result_present is True
    assert result.return_value == "actual result"


@pytest.mark.parametrize(
    ("code", "exit_code", "exception_type"),
    [
        ("def solve(:\n    pass\n", 125, "SyntaxError"),
        ("def solve():\n    return missing_name\n", 1, "NameError"),
    ],
)
def test_syntax_and_runtime_failures_are_observed(sandbox, code, exit_code, exception_type):
    result = sandbox.execute(ExecutionRequest(code=code))
    assert result.infrastructure_error is None
    assert result.exit_code == exit_code
    assert result.result_present is False
    assert result.exception_type == exception_type


def test_host_filesystem_is_not_mounted(sandbox, tmp_path):
    canary = tmp_path / "host-only.txt"
    canary.write_text("host canary", encoding="utf-8")
    code = (
        "def solve(path):\n"
        "    try:\n"
        "        with open(path, encoding='utf-8') as source:\n"
        "            return source.read()\n"
        "    except OSError:\n"
        "        return 'blocked'\n"
    )
    result = sandbox.execute(ExecutionRequest(code=code, arguments=[str(canary)]))
    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.return_value == "blocked"
    assert canary.read_text(encoding="utf-8") == "host canary"


def test_external_network_is_disabled(sandbox):
    code = (
        "def solve():\n"
        "    import socket\n"
        "    connection = socket.socket()\n"
        "    connection.settimeout(1)\n"
        "    try:\n"
        "        connection.connect(('203.0.113.1', 80))\n"
        "    except OSError:\n"
        "        return 'blocked'\n"
        "    finally:\n"
        "        connection.close()\n"
        "    return 'connected'\n"
    )
    result = sandbox.execute(ExecutionRequest(code=code, timeout_seconds=2))
    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.return_value == "blocked"


def test_timeout_and_output_limit_terminate_container(sandbox):
    timeout = sandbox.execute(
        ExecutionRequest(code="def solve():\n    while True:\n        pass\n", timeout_seconds=0.5)
    )
    assert timeout.infrastructure_error is None
    assert timeout.timed_out is True
    assert timeout.duration_seconds < 5

    flood = sandbox.execute(
        ExecutionRequest(code="print('x' * 100000)\n", mode="script", timeout_seconds=2)
    )
    assert flood.infrastructure_error is None
    assert flood.output_limited is True
    assert flood.duration_seconds < 5


def test_memory_and_process_limits_are_observable(sandbox):
    memory = sandbox.execute(ExecutionRequest(
        code=(
            "def solve():\n"
            "    try:\n"
            "        bytearray(512 * 1024 * 1024)\n"
            "    except MemoryError:\n"
            "        return 'limited'\n"
            "    return 'not-limited'\n"
        ),
        timeout_seconds=5,
    ))
    assert memory.infrastructure_error is None
    assert memory.oom_killed or memory.return_value == "limited"

    process = sandbox.execute(ExecutionRequest(
        code=(
            "def solve():\n"
            "    import os, signal, time\n"
            "    children = []\n"
            "    limited = False\n"
            "    try:\n"
            "        for _ in range(40):\n"
            "            pid = os.fork()\n"
            "            if pid == 0:\n"
            "                time.sleep(3)\n"
            "                os._exit(0)\n"
            "            children.append(pid)\n"
            "    except OSError:\n"
            "        limited = True\n"
            "    finally:\n"
            "        for pid in children:\n"
            "            try: os.kill(pid, signal.SIGKILL)\n"
            "            except OSError: pass\n"
            "        for pid in children:\n"
            "            try: os.waitpid(pid, 0)\n"
            "            except OSError: pass\n"
            "    return {'limited': limited, 'children': len(children)}\n"
        ),
        timeout_seconds=5,
    ))
    assert process.infrastructure_error is None
    assert process.exit_code == 0
    assert process.return_value["limited"] is True
    assert process.return_value["children"] < 40


def test_every_execution_container_is_removed(sandbox):
    before = _project_containers()
    result = sandbox.execute(ExecutionRequest(code="def solve():\n    return 1\n"))
    assert result.infrastructure_error is None
    assert _project_containers() == before
