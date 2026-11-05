"""Bounded request and result contracts for the execution tool."""

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any

_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MAX_CODE_BYTES = 16 * 1024
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_FIXTURE_BYTES = 64 * 1024
MAX_FIXTURE_TOTAL_BYTES = 128 * 1024
MAX_RAW_REQUEST_BYTES = 512 * 1024
MAX_TIMEOUT_SECONDS = 30.0


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("request fields must be finite JSON data") from exc


@dataclass(frozen=True)
class ExecutionRequest:
    """Candidate input. It deliberately has no expected-result or test fields."""

    code: str
    mode: str = "function"
    entrypoint: str = "solve"
    arguments: list[Any] = field(default_factory=list)
    stdin: str = ""
    script_args: list[str] = field(default_factory=list)
    fixtures: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0
    compile_only: bool = False

    def to_payload(self) -> bytes:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("candidate code must be a nonempty string")
        if len(self.code.encode("utf-8")) > MAX_CODE_BYTES:
            raise ValueError("candidate code exceeds the 16 KiB limit")
        if not isinstance(self.mode, str) or self.mode not in {"function", "script"}:
            raise ValueError("mode must be function or script")
        if not isinstance(self.entrypoint, str) or not self.entrypoint.isidentifier():
            raise ValueError("entrypoint must be a Python identifier")
        if not isinstance(self.arguments, list) or len(_json_bytes(self.arguments)) > MAX_ARGUMENT_BYTES:
            raise ValueError("arguments must be a JSON array within 64 KiB")
        if not isinstance(self.stdin, str) or len(self.stdin.encode("utf-8")) > 64 * 1024:
            raise ValueError("stdin must be UTF-8 text within 64 KiB")
        if not isinstance(self.script_args, list) or any(
            not isinstance(arg, str) or len(arg) > 1024 for arg in self.script_args
        ):
            raise ValueError("script_args must contain short strings")
        if type(self.compile_only) is not bool:
            raise ValueError("compile_only must be a boolean")
        if (isinstance(self.timeout_seconds, bool) or
                not isinstance(self.timeout_seconds, (int, float)) or
                not 0.1 <= self.timeout_seconds <= MAX_TIMEOUT_SECONDS):
            raise ValueError("timeout_seconds must be between 0.1 and 30 seconds")
        if not isinstance(self.fixtures, dict) or len(self.fixtures) > 4:
            raise ValueError("fixtures must be an object with at most four files")
        total = 0
        for name, content in self.fixtures.items():
            if (not isinstance(name, str) or not _FILENAME.fullmatch(name) or
                    "/" in name or "\\" in name or name in {"solution.py", "request.json"}):
                raise ValueError("fixture names must be safe, flat filenames")
            if not isinstance(content, str):
                raise ValueError("fixture contents must be UTF-8 text")
            size = len(content.encode("utf-8"))
            if size > MAX_FIXTURE_BYTES:
                raise ValueError("each fixture is limited to 64 KiB")
            total += size
        if total > MAX_FIXTURE_TOTAL_BYTES:
            raise ValueError("all fixtures together are limited to 128 KiB")
        payload = {
            "code": self.code,
            "mode": self.mode,
            "entrypoint": self.entrypoint,
            "arguments": self.arguments,
            "stdin": self.stdin,
            "script_args": self.script_args,
            "fixtures": self.fixtures,
            "compile_only": self.compile_only,
        }
        encoded = _json_bytes(payload)
        if len(encoded) > MAX_RAW_REQUEST_BYTES:
            raise ValueError("execution request exceeds 512 KiB")
        return encoded


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    output_limited: bool = False
    oom_killed: bool = False
    infrastructure_error: str | None = None
    protocol_error: str | None = None
    result_present: bool = False
    return_value: Any = None
    exception_type: str | None = None
    exception: str | None = None

    def to_dict(self):
        return asdict(self)
