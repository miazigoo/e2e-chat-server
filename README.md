# E2E Chat Server

Production-oriented backend for secure 1:1 Android and desktop chat.

## Stack

- FastAPI
- PostgreSQL
- Redis
- RabbitMQ
- Celery
- MinIO
- Firebase Cloud Messaging
- Prometheus / Grafana / Loki / OTel / Jaeger
- Caddy

---

# Quick start

## Local development

```bash
cp .env.example .env
docker compose up --build
```

## Useful commands

```bash
make test-unit
make test-integration
make lint
```
---
## API docs
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI schema: http://localhost:8000/openapi.json
---
## Health
- Liveness: http://localhost:8000/health/live
- Readiness: http://localhost:8000/health/ready
---
## Auth model
### Tokens
#### Bootstrap token
Used only to register the first device or bootstrap a new device.
#### Access token
Used for authenticated API and WebSocket.
#### Refresh token
Used to rotate access tokens.

---
## Required headers
For device-bound endpoints:
```http
Authorization: Bearer <access_token>
X-Device-UUID: <device_uuid>
```
Optional:
```http
X-Request-ID: <uuid>
```
---
## Main client flows
### 1. Register
#### Request
`POST /api/v1/auth/register`
```json
{
  "nickname": "@alice",
  "password": "supersecret123",
  "email": "alice@example.com",
  "email_2fa_enabled": true
}
```
#### Response
```json
{
  "ok": true,
  "data": {
    "user_id": 1,
    "nickname": "@alice",
    "requires_device_registration": true,
    "bootstrap_token": "jwt.bootstrap.token",
    "bootstrap_expires_in": 900
  },
  "meta": {
    "request_id": "..."
  }
}
```

### 2. Bootstrap device
#### Request
`POST /api/v1/auth/bootstrap`
Headers:
```http
Authorization: Bearer <bootstrap_token>
```
Body:
```json
{
  "device_uuid": "android-device-uuid",
  "device_name": "Pixel 8",
  "platform": "android",
  "app_version": "1.0.0",
  "fcm_token": "fcm-token",
  "public_identity_key": "base64-identity-key",
  "public_signing_key": "base64-signing-key",
  "signed_prekey": "base64-signed-prekey",
  "signed_prekey_signature": "base64-signature",
  "one_time_prekeys": [
    {
      "prekey_id": 1,
      "public_prekey": "base64-prekey-1"
    },
    {
      "prekey_id": 2,
      "public_prekey": "base64-prekey-2"
    }
  ]
}

```
#### Response
```json
{
  "ok": true,
  "data": {
    "device_id": 10,
    "device_uuid": "android-device-uuid",
    "is_active": true,
    "prekeys_count": 2,
    "last_seen_at": "2026-04-20T12:00:00+00:00"
  },
  "meta": {}
}
```

### 3. Login
#### Request
`POST /api/v1/auth/login`
```json
{
  "nickname": "@alice",
  "password": "supersecret123",
  "device_uuid": "android-device-uuid"
}
```

#### Response without 2FA
```json
{
  "ok": true,
  "data": {
    "requires_email_code": false,
    "requires_bootstrap": false,
    "access_token": "jwt.access.token",
    "refresh_token": "jwt.refresh.token",
    "expires_in": 900
  },
  "meta": {}
}

```

#### Response with 2FA
```json
{
  "ok": true,
  "data": {
    "requires_email_code": true,
    "requires_bootstrap": false,
    "login_challenge_id": "uuid",
    "email_masked": "a***@example.com"
  },
  "meta": {}
}

```

`debug_code` is intentionally disabled by default and should only be enabled in non-production via `ALLOW_DEBUG_EMAIL_CODES=true`.
To actually deliver email 2FA codes, configure SMTP with `SMTP_HOST` and
`SMTP_FROM_EMAIL` plus optional `SMTP_USERNAME` / `SMTP_PASSWORD`.

### 4. Verify email code
#### Request
`POST /api/v1/auth/login/verify-email-code`
```json
{
  "login_challenge_id": "uuid",
  "code": "123456",
  "device_uuid": "android-device-uuid"
}

```
#### Response
```json
{
  "ok": true,
  "data": {
    "requires_bootstrap": false,
    "access_token": "jwt.access.token",
    "refresh_token": "jwt.refresh.token",
    "expires_in": 900
  },
  "meta": {}
}

```
If device is not registered yet:
```json
{
  "ok": true,
  "data": {
    "requires_bootstrap": true,
    "bootstrap_token": "jwt.bootstrap.token",
    "bootstrap_expires_in": 900
  },
  "meta": {}
}

```

### 5. Refresh tokens
#### Request
`POST /api/v1/auth/refresh`
```json
{
  "refresh_token": "jwt.refresh.token"
}

```
#### Response
```json
{
  "ok": true,
  "data": {
    "access_token": "new.jwt.access.token",
    "refresh_token": "new.jwt.refresh.token",
    "expires_in": 900
  },
  "meta": {}
}

```

### 6. Logout
#### Request
`POST /api/v1/auth/logout`
Headers:
```http
Authorization: Bearer <access_token>
```

#### Response
```json
{
  "ok": true,
  "data": {
    "message": "Logged out",
    "revoked_sessions": 1
  },
  "meta": {}
}

```
---
## Device endpoints
### List devices
`GET /api/v1/devices`

Returns the user's active approved devices. Use it for the account devices screen.

### Device approval requests
When login is attempted from an unknown device and the account already has an
active device, auth returns:
```json
{
  "ok": true,
  "data": {
    "requires_email_code": false,
    "requires_totp": false,
    "requires_bootstrap": false,
    "requires_device_approval": true,
    "device_approval_request_id": "uuid"
  },
  "meta": {}
}
```

Already approved devices receive realtime event `device_approval_requested` and,
when FCM is configured, a push notification.

List pending requests:
`GET /api/v1/devices/authorization-requests`

Approve or deny a new device:
- `POST /api/v1/devices/authorization-requests/{request_id}/approve`
- `POST /api/v1/devices/authorization-requests/{request_id}/deny`

After approval, the new device repeats login and receives a bootstrap token.

### Heartbeat
`POST /api/v1/devices/heartbeat`
Response:
```json
{
  "ok": true,
  "data": {
    "device_id": 10,
    "device_uuid": "android-device-uuid",
    "status": "online",
    "last_seen_at": "2026-04-20T12:00:00+00:00"
  },
  "meta": {}
}

```

### Update FCM token
`POST /api/v1/devices/fcm-token`
```json
{
  "fcm_token": "new-fcm-token"
}

```
### Revoke current device
`DELETE /api/v1/devices/current`

### Revoke another device
`DELETE /api/v1/devices/{device_id}`

---
## Keys
### Get recipient key bundles for all approved devices
`GET /api/v1/keys/bundles/{user_id}`

Returns key bundles for every active approved device of the target user. Use this
for multi-device fan-out before sending a message.

Response:
```json
{
  "ok": true,
  "data": {
    "user_id": 2,
    "devices": [
      {
        "user_id": 2,
        "device_id": 20,
        "requested_by_device_id": 10,
        "registration_id": 2001,
        "public_identity_key": "base64",
        "public_signing_key": "base64",
        "signed_prekey_id": 1,
        "signed_prekey": "base64",
        "signed_prekey_signature": "base64",
        "one_time_prekey": {
          "prekey_id": 123,
          "public_prekey": "base64"
        },
        "prekeys_remaining": 49
      }
    ]
  },
  "meta": {}
}
```

### Get recipient key bundle
`GET /api/v1/keys/bundle/{user_id}`

Compatibility endpoint for one device. Prefer `/bundles/{user_id}` for current
multi-device clients.

Response:
```json
{
  "ok": true,
  "data": {
    "user_id": 2,
    "device_id": 20,
    "requested_by_device_id": 10,
    "registration_id": 2001,
    "public_identity_key": "base64",
    "public_signing_key": "base64",
    "signed_prekey_id": 1,
    "signed_prekey": "base64",
    "signed_prekey_signature": "base64",
    "one_time_prekey": {
      "prekey_id": 123,
      "public_prekey": "base64"
    },
    "prekeys_remaining": 49
  },
  "meta": {}
}

```

### Refill prekeys
`POST /api/v1/keys/prekeys/refill`
```json
{
  "prekeys": [
    {
      "prekey_id": 1001,
      "public_prekey": "base64"
    }
  ]
}

```

### Rotate signed prekey
`POST /api/v1/keys/signed-prekey/rotate`
```json
{
  "signed_prekey": "base64",
  "signed_prekey_signature": "base64"
}
```
---
## Users
### Search users
`GET /api/v1/users/search?q=@al`
### User safety
`GET /api/v1/users/{user_id}/safety`
Response:
```json
{
  "ok": true,
  "data": {
    "user_id": 2,
    "nickname": "@bob",
    "can_start_conversation": true,
    "is_deleted": false,
    "pending_deletion": false,
    "has_active_device": true,
    "supports_encrypted_chat": true,
    "safety_code_available": true
  },
  "meta": {}
}

```
---
## Conversations
### Create conversation
`POST /api/v1/conversations`
```json
{
  "recipient_user_id": 2,
  "title": "Secret chat",
  "protection_mode": "normal",
  "message_ttl_days": 30,
  "delete_after_read_seconds": null
}

```

### List conversations
`GET /api/v1/conversations`
### Get conversation
`GET /api/v1/conversations/{conversation_id}`
### Update conversation
`PATCH /api/v1/conversations/{conversation_id}`
```json
{
  "title": "Updated title",
  "message_ttl_days": 14,
  "delete_after_read_seconds": 3600
}

```

### Clear local
`POST /api/v1/conversations/{conversation_id}/clear-local`
### Clear global
`POST /api/v1/conversations/{conversation_id}/clear-global`
```json
{
  "reason": "cleanup"
}

```
---
## Files
### Strategy
#### Variant A
Client uploads encrypted attachment blobs directly to final attachments bucket using presigned PUT URL.

There is no runtime temp-bucket move/copy step in the normal message flow.
### Create upload session
`POST /api/v1/files/upload-sessions`
```json
{
  "conversation_id": 123,
  "files_expected_count": 2
}

```
### Init attachments
`POST /api/v1/files/upload-sessions/{session_id}/attachments/init`
```json
{
  "items": [
    {
      "encrypted_file_name": "file.enc",
      "file_size": 123456,
      "mime_hint": "application/octet-stream",
      "sha256_encrypted_blob": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "encrypted_metadata": {
        "preview": "..."
      }
    }
  ]
}

```

#### Response
```json
{
  "ok": true,
  "data": {
    "session_id": 1,
    "session_uuid": "uuid",
    "items": [
      {
        "attachment_id": 10,
        "attachment_uuid": "uuid",
        "storage_key": "attachments/<upload_session_uuid>/<random>",
        "bucket_name": "chat-attachments-prod",
        "upload_status": "init",
        "expires_at": "2026-04-20T12:00:00+00:00",
        "upload_url": "https://minio-presigned-put-url",
        "upload_method": "PUT",
        "upload_headers": {}
      }
    ]
  },
  "meta": {}
}

```

#### Upload blob
Client performs HTTP `PUT` directly to `upload_url`.
#### Complete upload session
`POST /api/v1/files/upload-sessions/{session_id}/complete`
```json
{
  "attachment_ids": [10]
}

```

#### List message attachments
`GET /api/v1/files/messages/{message_id}/attachments`

#### List attachments for multiple messages
`POST /api/v1/files/messages/attachments/batch`
```json
{
  "message_ids": [99, 100]
}
```

### Get attachment metadata and download URL
`GET /api/v1/files/attachments/{attachment_id}`
Response:
```json
{
  "ok": true,
  "data": {
    "attachment_id": 10,
    "attachment_uuid": "uuid",
    "message_id": 99,
    "file_size": 123456,
    "bucket_name": "chat-attachments-prod",
    "storage_key": "attachments/...",
    "upload_status": "linked",
    "created_at": "2026-04-20T12:00:00+00:00",
    "expires_at": null,
    "deleted_at": null,
    "media_tags": [
      {
        "tag_id": 7,
        "conversation_id": 123,
        "name": "Receipts",
        "color": "#22c55e",
        "created_by_user_id": 1,
        "created_at": "2026-04-20T12:00:00+00:00",
        "updated_at": "2026-04-20T12:00:00+00:00"
      }
    ],
    "can_download": true,
    "download_url": "https://minio-presigned-get-url",
    "download_url_expires_in": 300
  },
  "meta": {}
}

```

### Media tags
Conversation media tags are server-visible labels for uploaded attachments. They
are intended for folders/filters such as receipts, card barcodes or photos.

Manage tags in a conversation:
- `GET /api/v1/conversations/{conversation_id}/media-tags`
- `POST /api/v1/conversations/{conversation_id}/media-tags`
- `PATCH /api/v1/conversations/{conversation_id}/media-tags/{tag_id}`
- `DELETE /api/v1/conversations/{conversation_id}/media-tags/{tag_id}`

Create tag:
```json
{
  "name": "Receipts",
  "color": "#22c55e"
}
```

Assign tags to an existing attachment:
- `POST /api/v1/files/attachments/{attachment_id}/media-tags` adds tags
- `PUT /api/v1/files/attachments/{attachment_id}/media-tags` replaces all tags
- `DELETE /api/v1/files/attachments/{attachment_id}/media-tags/{tag_id}` removes one tag

Request body:
```json
{
  "tag_ids": [7, 8]
}
```

### Android APK releases
#### Upload new APK release
`POST /api/v1/files/apk/upload`

No JWT auth is required. Pass the release token using one of:
- multipart form field `token`
- header `X-APK-Upload-Token`
- query param `token`

Multipart fields:
- `version_name`
- `version_code`
- `changelog` (optional)
- `file` (`.apk`)

Example:
```bash
curl -X POST http://localhost:8000/api/v1/files/apk/upload \
  -H "X-APK-Upload-Token: <apk_upload_token>" \
  -F "version_name=1.2.3" \
  -F "version_code=123" \
  -F "changelog=Bug fixes and performance improvements" \
  -F "file=@app-release.apk;type=application/vnd.android.package-archive"
```

Helper script:
```bash
APK_UPLOAD_BASE_URL="https://example.com" \
APK_UPLOAD_TOKEN="<apk_upload_token>" \
APK_PATH="../-e2e-chat-client/app/build/outputs/apk/release/app-release.apk" \
APK_METADATA_PATH="../-e2e-chat-client/app/build/outputs/apk/release/output-metadata.json" \
APK_CHANGELOG="Release build" \
scripts/upload_apk_release.sh
```

Set `APK_UPLOAD_INSECURE=1` when uploading to a server that uses a self-signed
HTTPS certificate. If `APK_METADATA_PATH` is present, the script reads
`version_name` and `version_code` from Gradle `output-metadata.json`; otherwise
set `APK_VERSION_NAME` and `APK_VERSION_CODE` explicitly.

#### Get latest APK metadata
`GET /api/v1/files/apk/latest`

#### Check client version against latest APK
`GET /api/v1/files/apk/check?version_code=120`

Example response:
```json
{
  "ok": true,
  "data": {
    "current_version_code": 120,
    "latest_version_code": 123,
    "update_available": true,
    "release": {
      "platform": "android",
      "version_name": "1.2.3",
      "version_code": 123,
      "file_name": "app-release.apk",
      "file_size": 73400320,
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "changelog": "Bug fixes and performance improvements",
      "content_type": "application/vnd.android.package-archive",
      "uploaded_at": "2026-04-25T12:00:00+00:00",
      "download_url": "https://minio-presigned-get-url",
      "download_url_expires_in": 300
    }
  },
  "meta": {}
}
```

---
## User profile
### Get my profile
`GET /api/v1/users/me`

### Update my profile
`PATCH /api/v1/users/me`
```json
{
  "full_name": "Alice Example",
  "bio": "Android user",
  "language_code": "ru",
  "theme": "dark",
  "push_notifications_enabled": true,
  "apk_update_notifications_enabled": true
}
```

### Upload avatar
`POST /api/v1/users/me/avatar`

Multipart field:
- `file` image file

### Delete avatar
`DELETE /api/v1/users/me/avatar`

### Get another user's public profile
`GET /api/v1/users/{user_id}/profile`
---
## Messages
### Send message
`POST /api/v1/messages/send`
```json
{
  "conversation_id": 123,
  "recipient_user_id": 2,
  "message_uuid": "client-generated-uuid",
  "reply_to_message_id": null,
  "message_type": "text",
  "ciphertext": "base64ciphertext",
  "ciphertext_version": 1,
  "encryption_mode": "signal",
  "nonce": "base64nonce",
  "aad_hash": null,
  "client_created_at": "2026-04-20T12:00:00+00:00",
  "expires_at": "2026-05-20T12:00:00+00:00",
  "auto_delete_after_read_seconds": null,
  "attachment_ids": [10],
  "attachment_tag_ids": [7],
  "device_payloads": [
    {
      "device_id": 20,
      "ciphertext": "base64ciphertext-for-device-20",
      "ciphertext_version": 1,
      "nonce": "base64nonce",
      "aad_hash": null
    }
  ]
}

```
#### Response
```json
{
  "ok": true,
  "data": {
    "message_id": 999,
    "message_uuid": "client-generated-uuid",
    "conversation_id": 123,
    "recipient_user_id": 2,
    "recipient_device_id": 20,
    "recipient_device_ids": [20, 21],
    "server_received_at": "2026-04-20T12:00:01+00:00",
    "delivery_status": "server_received",
    "is_idempotent_replay": false
  },
  "meta": {}
}

```

For E2E multi-device delivery, the client should fetch `/api/v1/keys/bundles/{recipient_user_id}`,
encrypt a per-device payload and send it in `device_payloads`. The server stores
fan-out payloads for all approved active recipient devices and returns
`recipient_device_ids`.

### Forward messages
`POST /api/v1/messages/forward`
```json
{
  "conversation_id": 123,
  "recipient_user_id": 2,
  "message_ids": [999, 1000],
  "client_created_at": "2026-04-25T12:10:00+00:00"
}
```

### Search inside conversation
`GET /api/v1/messages/conversations/{conversation_id}/search?q=query&limit=50`

Note:
Server-side search is limited to fields visible to the backend, such as `ciphertext`
and attachment metadata. In a true E2E plaintext-search scenario, a separate client-side
or encrypted search index is still needed.

### Shared media / links / files
`GET /api/v1/messages/conversations/{conversation_id}/shared?tab=media&limit=50`

Allowed `tab` values:
- `media`
- `links`
- `files`

Response also includes counts for all tabs so the client can render Telegram-like tabs.
For media tags, pass `tag_id`:
`GET /api/v1/messages/conversations/{conversation_id}/shared?tab=media&tag_id=7&limit=50`

### Pin message
`POST /api/v1/messages/conversations/{conversation_id}/pin/{message_id}`

### Unpin message
`DELETE /api/v1/messages/conversations/{conversation_id}/pin`

### List messages
`GET /api/v1/messages/conversations/{conversation_id}?before_id=1000&limit=50`

History supports cursor and anchor loading:
- `before_id` for older messages
- `after_id` for newer messages
- `anchor_id` to load around a specific message, for example when opening a pinned message

Each message item now may include:
- `sender_device_id`
- `device_payload`
- `reply_to_message_id`
- `forward_from_message_id`
- `reply_preview`
- `forward_preview`

`sender_device_id` is also present in reply, forward and pinned previews so the
client can deterministically pick the sender session for decryption.

### Delivered ack
`POST /api/v1/messages/{message_id}/delivered`
```json
{
  "delivered_at": "2026-04-20T12:00:05+00:00"
}

```

### Read ack
`POST /api/v1/messages/{message_id}/read`
```json
{
  "read_at": "2026-04-20T12:00:10+00:00"
}

```

### Delete local
`POST /api/v1/messages/delete-local`
```json
{
  "conversation_id": 123,
  "message_ids": [999]
}

```

### Delete global
`POST /api/v1/messages/delete-global`
```json
{
  "conversation_id": 123,
  "message_ids": [999]
}

```
---
## Sync
### Events feed
`GET /api/v1/sync/conversations/{conversation_id}/events?after_event_id=100&limit=100`

---
## WebSocket
### Connect
#### URL
```text
ws://localhost:8000/api/v1/ws?token=<access_token>&device_uuid=<device_uuid>
```

or use headers:
```text
Authorization: Bearer <access_token>
X-Device-UUID: <device_uuid>
```

### Supported client messages
#### Ping
```json
{
  "type": "ping"
}

```

#### Who am I
```json
{
  "type": "whoami"
}

```
#### Subscribe to conversation
```json
{
  "type": "subscribe_conversation",
  "conversation_id": 123
}

```

#### Unsubscribe from conversation
```json
{
  "type": "unsubscribe_conversation",
  "conversation_id": 123
}

```

### Server events
#### Connected
```json
{
  "type": "connected",
  "user_id": 1,
  "device_id": 10,
  "session_id": "uuid"
}

```
#### Realtime conversation event
```json
{
  "type": "conversation.event",
  "conversation_id": 123,
  "event": {
    "event_id": 555,
    "event_uuid": "uuid",
    "event_type": "message_created",
    "actor_user_id": 1,
    "actor_device_id": 10,
    "target_message_id": 999,
    "payload": {
      "message_id": 999
    },
    "created_at": "2026-04-20T12:00:01+00:00"
  }
}

```
#### App update available
```json
{
  "type": "app_update_available",
  "release": {
    "platform": "android",
    "version_name": "1.2.3",
    "version_code": 123,
    "file_name": "app-release.apk",
    "file_size": 73400320,
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "changelog": "Bug fixes and performance improvements",
    "content_type": "application/vnd.android.package-archive",
    "uploaded_at": "2026-04-25T12:00:00+00:00"
  }
}
```
#### Message pinned
```json
{
  "type": "conversation.event",
  "conversation_id": 123,
  "event": {
    "event_type": "message_pinned",
    "target_message_id": 999,
    "payload": {
      "message_id": 999,
      "pinned_message_id": 999,
      "preview": {
        "message_id": 999,
        "message_uuid": "uuid",
        "sender_user_id": 1,
        "message_type": "text",
        "ciphertext": "ciphertext",
        "has_attachments": false,
        "client_created_at": "2026-04-25T12:00:00+00:00"
      }
    }
  }
}
```
### Error
```json
{
  "type": "error",
  "code": "CONVERSATION_NOT_FOUND",
  "message": "Conversation not found"
}

```
---
## Android integration checklist
### Before login
- register user or get existing nickname/password
- bootstrap first device if needed

### After login
- save:
  - access token
  - refresh token
  - device_uuid
- always send:
  - `Authorization: Bearer ...` 
  - `X-Device-UUID: ...`
### Sending file
1. create upload session
2. init attachments
3. upload encrypted blob(s) to presigned PUT URL(s)
4. complete upload session
5. send message with `attachment_ids`
### Receiving message
1. get realtime event from WebSocket or fetch sync events
2. list message attachments if needed
3. get attachment metadata
4. download encrypted blob by presigned GET URL
5. decrypt locally on device

---
## Notes
- Server stores only ciphertext and encrypted blobs.
- Server never sees plaintext message or plaintext file.
- Shared secret mode is client-side only.
- Official Android client must process delete/read/delivered events.
---



### Pre-commit
```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit install --hook-type pre-push
# запуск в ручную
pre-commit run --all-files
```

### Swagger
```bash
# запуск приложения
docker compose up --build
```

```http
# Открываешь
http://localhost:8000/docs
```
Там будет Swagger UI.

### Полезные ссылки
```http
# Swagger UI:
http://localhost:8000/docs

# ReDoc:
http://localhost:8000/redoc

# OpenAPI schema:
http://localhost:8000/openapi.json

# Health:
http://localhost:8000/health
```

---
## Автозапуск на сервере (systemd)
Включил автозапуск после перезагрузки сервера через systemd:
- Создан unit: `/etc/systemd/system/e2e-chat-server.service`
- Включен: `systemctl enable e2e-chat-server.service`
- Активен: `active (exited)` (это нормально для `Type=oneshot` + `RemainAfterExit=yes`)
- Docker daemon тоже включен и активен (`enabled`, `active`)
