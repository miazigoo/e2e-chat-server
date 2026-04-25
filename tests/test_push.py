from app.core.push import (
    build_app_update_push_payload,
    build_generic_event_push_payload,
    build_new_message_push_payload,
)


def test_build_new_message_push_payload() -> None:
    payload = build_new_message_push_payload(
        conversation_id=10,
        message_id=20,
    )
    assert payload["type"] == "new_message"
    assert payload["conversation_id"] == "10"
    assert payload["message_id"] == "20"


def test_build_generic_event_push_payload() -> None:
    payload = build_generic_event_push_payload(
        conversation_id=77,
        event_type="message_read",
    )
    assert payload["type"] == "conversation_event"
    assert payload["conversation_id"] == "77"
    assert payload["event_type"] == "message_read"


def test_build_app_update_push_payload() -> None:
    payload = build_app_update_push_payload(
        version_name="1.2.3",
        version_code=123,
    )
    assert payload["type"] == "app_update_available"
    assert payload["platform"] == "android"
    assert payload["version_name"] == "1.2.3"
    assert payload["version_code"] == "123"
