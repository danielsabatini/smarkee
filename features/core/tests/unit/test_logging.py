import json
import logging

from core.logging_config import JsonFormatter


def record(message: str, *, error: Exception | None = None, **extra: object) -> logging.LogRecord:
    exc_info = None
    if error is not None:
        try:
            raise error
        except Exception as raised:
            exc_info = (type(raised), raised, raised.__traceback__)
    log_record = logging.LogRecord("core.test", logging.INFO, __file__, 10, message, (), exc_info)
    for key, value in extra.items():
        setattr(log_record, key, value)
    return log_record


def test_event_is_one_json_line_with_context_keys() -> None:
    line = JsonFormatter().format(
        record("requested handled", resource_type="organization", outcome="accepted")
    )
    payload = json.loads(line)
    assert "\n" not in line
    assert payload["message"] == "requested handled"
    assert payload["level"] == "INFO"
    assert payload["resource_type"] == "organization"
    assert payload["outcome"] == "accepted"
    assert payload["time"].endswith("+00:00")


def test_exception_message_is_never_logged_because_it_may_carry_values() -> None:
    line = JsonFormatter().format(
        record("falha", error=ValueError("Key (email)=(ana@example.com) already exists"))
    )
    payload = json.loads(line)
    assert payload["error_type"] == "ValueError"
    assert "error_location" in payload
    assert "ana@example.com" not in line
