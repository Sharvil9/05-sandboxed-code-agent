import json

import pytest

from sandbox_agent.contracts import ExecutionRequest, ExecutionResult


def test_request_serializes_only_candidate_inputs():
    request = ExecutionRequest(code="def solve(value):\n    return value\n", arguments=[3])
    payload = json.loads(request.to_payload())
    assert set(payload) == {
        "code", "mode", "entrypoint", "arguments", "stdin", "script_args",
        "fixtures", "compile_only",
    }
    assert "expected" not in payload and "tests" not in payload


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"code": "x" * (16 * 1024 + 1)}, "code exceeds"),
        ({"mode": []}, "mode must"),
        ({"entrypoint": "not-valid!"}, "entrypoint"),
        ({"timeout_seconds": 30.1}, "timeout_seconds"),
        ({"fixtures": {"../escape.txt": "x"}}, "fixture names"),
        ({"arguments": [float("nan")]}, "finite JSON"),
    ],
)
def test_request_rejects_unsupported_or_oversized_values(changes, message):
    fields = {"code": "def solve():\n    return None\n"}
    fields.update(changes)
    with pytest.raises(ValueError, match=message):
        ExecutionRequest(**fields).to_payload()


def test_execution_result_is_json_serializable():
    result = ExecutionResult(
        execution_id="run-1", exit_code=0, stdout="ok", stderr="",
        duration_seconds=0.25, result_present=True, return_value={"answer": 42},
    )
    encoded = json.dumps(result.to_dict(), allow_nan=False)
    assert json.loads(encoded)["return_value"] == {"answer": 42}
