import struct

import pytest

from sandbox_agent.sandbox import MAX_OUTPUT_BYTES, _OutputLimitExceeded, _frame_chunks


def _frame(stream: int, content: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + struct.pack(">I", len(content)) + content


def test_docker_multiplexed_frames_are_separated_and_consumed():
    buffer = bytearray(_frame(1, b"out") + _frame(2, b"err"))
    first = next(_frame_chunks(buffer, 0, MAX_OUTPUT_BYTES))
    second = next(_frame_chunks(buffer, len(first[1]), MAX_OUTPUT_BYTES))
    assert first == (1, b"out")
    assert second == (2, b"err")
    assert buffer == bytearray()


def test_docker_frame_output_limit_is_checked_from_header():
    oversized_header = bytes([1, 0, 0, 0]) + struct.pack(">I", MAX_OUTPUT_BYTES + 1)
    with pytest.raises(_OutputLimitExceeded):
        next(_frame_chunks(bytearray(oversized_header), 0, MAX_OUTPUT_BYTES))


def test_docker_frame_rejects_unknown_stream_channel():
    invalid = bytes([3, 0, 0, 0]) + struct.pack(">I", 0)
    with pytest.raises(ValueError, match="invalid Docker attach"):
        next(_frame_chunks(bytearray(invalid), 0, MAX_OUTPUT_BYTES))
