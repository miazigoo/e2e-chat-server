from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _latest_payload() -> dict[str, Any]:
    return {
        "platform": "android",
        "version_name": "1.2.3",
        "version_code": 123,
        "file_name": "chat.apk",
        "file_size": 1024,
        "sha256": "a" * 64,
        "changelog": "Bug fixes",
        "content_type": "application/vnd.android.package-archive",
        "uploaded_at": datetime.now(timezone.utc),
        "download_url": "https://example.com/chat.apk",
        "download_url_expires_in": 300,
    }


def test_upload_apk_endpoint_accepts_form_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_upload_android_apk_release(
        session: Any,
        *,
        upload_token: str | None,
        version_name: str,
        version_code: int,
        changelog: str | None,
        file: Any,
    ) -> dict[str, Any]:
        assert upload_token == "secret-token"
        assert version_name == "1.2.3"
        assert version_code == 123
        assert changelog == "Bug fixes"
        assert file.filename == "chat.apk"
        data = _latest_payload()
        return {
            "platform": data["platform"],
            "version_name": data["version_name"],
            "version_code": data["version_code"],
            "file_name": data["file_name"],
            "file_size": data["file_size"],
            "sha256": data["sha256"],
            "uploaded_at": data["uploaded_at"],
            "notified_devices": 7,
        }

    monkeypatch.setattr(
        "app.api.v1.files.upload_android_apk_release",
        fake_upload_android_apk_release,
    )

    response = client.post(
        "/api/v1/files/apk/upload",
        data={
            "token": "secret-token",
            "version_name": "1.2.3",
            "version_code": "123",
            "changelog": "Bug fixes",
        },
        files={
            "file": (
                "chat.apk",
                b"apk-binary",
                "application/vnd.android.package-archive",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["notified_devices"] == 7


def test_upload_apk_endpoint_accepts_header_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_upload_android_apk_release(
        session: Any,
        *,
        upload_token: str | None,
        version_name: str,
        version_code: int,
        changelog: str | None,
        file: Any,
    ) -> dict[str, Any]:
        assert upload_token == "header-secret"
        data = _latest_payload()
        return {
            "platform": data["platform"],
            "version_name": version_name,
            "version_code": version_code,
            "file_name": file.filename,
            "file_size": 1024,
            "sha256": "b" * 64,
            "uploaded_at": data["uploaded_at"],
            "notified_devices": 1,
        }

    monkeypatch.setattr(
        "app.api.v1.files.upload_android_apk_release",
        fake_upload_android_apk_release,
    )

    response = client.post(
        "/api/v1/files/apk/upload",
        headers={"X-APK-Upload-Token": "header-secret"},
        data={"version_name": "1.2.4", "version_code": "124"},
        files={
            "file": (
                "chat.apk",
                b"apk-binary",
                "application/vnd.android.package-archive",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["version_code"] == 124


def test_get_latest_apk_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_latest_android_apk_release(session: Any) -> dict[str, Any]:
        return _latest_payload()

    monkeypatch.setattr(
        "app.api.v1.files.get_latest_android_apk_release",
        fake_get_latest_android_apk_release,
    )

    response = client.get("/api/v1/files/apk/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["version_name"] == "1.2.3"
    assert body["data"]["download_url"] == "https://example.com/chat.apk"
