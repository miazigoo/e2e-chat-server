# Полная схема: PostgreSQL + Redis keys + MinIO model

## 1. Общая модель хранения

### PostgreSQL хранит
- пользователей;
- устройства;
- публичные ключи и prekeys;
- чаты;
- сообщения (ciphertext);
- статусы доставки и прочтения;
- события синхронизации;
- метаданные файлов;
- login lockout state;
- 2FA-журнал;
- операции purge.

### Redis хранит
- online/offline состояние;
- websocket routing;
- pub/sub события между backend-инстансами;
- счетчики непрочитанных;
- короткоживущие email-коды;
- распределённые локи;
- idempotency state;
- short-lived session flags.

### MinIO хранит
- только зашифрованные файловые blobs;
- multipart upload parts;
- временные объекты до финализации.

---

# 2. PostgreSQL: справочные ENUM-ы

## 2.1 user_status
```sql
active
frozen
pending_deletion
deleted
```

## 2.2 conversation_protection_mode
```sql
normal
shared_secret
```

## 2.3 message_type
```sql
text
file
service
system
```

## 2.4 encryption_mode
```sql
signal
signal_plus_shared_secret
```

## 2.5 delivery_status
```sql
server_received
push_queued
push_sent
device_delivered
read
failed
expired
purged
```

## 2.6 upload_status
```sql
init
uploading
uploaded
linked
failed
deleted
```

## 2.7 event_type
```sql
message_created
message_deleted_global
message_hidden_for_user
conversation_cleared_local
conversation_cleared_global
message_delivered
message_read
file_uploaded
file_deleted
participant_key_changed
chat_purged
```

## 2.8 auth_code_purpose
```sql
login_2fa
email_confirm
recovery
```

---

# 3. PostgreSQL: таблицы

## 3.1 users
```sql
id                          bigserial primary key
nickname                    varchar(64) not null unique
password_hash               text not null
email                       varchar(320) null
email_2fa_enabled           boolean not null default false
status                      varchar(32) not null default 'active'
failed_login_stage          smallint not null default 0
failed_login_count          smallint not null default 0
lock_until                  timestamptz null
created_at                  timestamptz not null default now()
updated_at                  timestamptz not null default now()
deleted_at                  timestamptz null
```

### Индексы
```sql
unique (nickname)
index (status)
index (lock_until)
```

---

## 3.2 devices
```sql
id                          bigserial primary key
user_id                     bigint not null references users(id) on delete cascade
device_uuid                 uuid not null unique
device_name                 varchar(128) null
platform                    varchar(32) not null default 'android'
is_active                   boolean not null default true
registered_at               timestamptz not null default now()
last_seen_at                timestamptz null
fcm_token                   text null
app_version                 varchar(64) null
public_identity_key         text not null
public_signing_key          text null
signed_prekey               text not null
signed_prekey_signature     text not null
prekeys_count               integer not null default 0
safety_number_version       integer not null default 1
revoked_at                  timestamptz null
```

### Ограничения
- один активный девайс на аккаунт;
- enforce через partial unique index:

```sql
unique (user_id) where is_active = true
```

---

## 3.3 device_prekeys
```sql
id                          bigserial primary key
device_id                   bigint not null references devices(id) on delete cascade
prekey_id                   integer not null
public_prekey               text not null
is_used                     boolean not null default false
created_at                  timestamptz not null default now()
used_at                     timestamptz null
```

### Индексы
```sql
unique (device_id, prekey_id)
index (device_id, is_used)
```

---

## 3.4 user_sessions
```sql
id                          bigserial primary key
user_id                     bigint not null references users(id) on delete cascade
device_id                   bigint not null references devices(id) on delete cascade
refresh_token_hash          text not null
issued_at                   timestamptz not null default now()
expires_at                  timestamptz not null
revoked_at                  timestamptz null
ip_address                  inet null
user_agent                  text null
```

### Индексы
```sql
index (user_id)
index (device_id)
index (expires_at)
```

---

## 3.5 conversations
```sql
id                          bigserial primary key
conversation_uuid           uuid not null unique
user_a_id                   bigint not null references users(id) on delete cascade
user_b_id                   bigint not null references users(id) on delete cascade
created_by_user_id          bigint not null references users(id) on delete restrict
title                       varchar(128) null
protection_mode             varchar(32) not null default 'normal'
message_ttl_days            integer null
delete_after_read_seconds   integer null
clear_policy                varchar(32) not null default 'global_allowed'
is_active                   boolean not null default true
is_purged                   boolean not null default false
created_at                  timestamptz not null default now()
updated_at                  timestamptz not null default now()
```

### Ограничения
```sql
check (user_a_id <> user_b_id)
```

### Индексы
```sql
index (user_a_id)
index (user_b_id)
index (is_purged)
index (updated_at desc)
```

---

## 3.6 conversation_participants
```sql
id                          bigserial primary key
conversation_id             bigint not null references conversations(id) on delete cascade
user_id                     bigint not null references users(id) on delete cascade
joined_at                   timestamptz not null default now()
left_at                     timestamptz null
cleared_up_to_event_id      bigint null
```

### Индексы
```sql
unique (conversation_id, user_id)
index (user_id, conversation_id)
```

---

## 3.7 messages
Рекомендуется делать range partitioning по `server_received_at` или `created_at`.

```sql
id                          bigserial primary key
message_uuid                uuid not null unique
conversation_id             bigint not null references conversations(id) on delete cascade
sender_user_id              bigint not null references users(id) on delete cascade
sender_device_id            bigint not null references devices(id) on delete restrict
recipient_user_id           bigint not null references users(id) on delete cascade
recipient_device_id         bigint not null references devices(id) on delete restrict
reply_to_message_id         bigint null references messages(id) on delete set null
message_type                varchar(32) not null
ciphertext                  text not null
ciphertext_version          smallint not null default 1
encryption_mode             varchar(64) not null
nonce                       text not null
aad_hash                    text null
client_created_at           timestamptz not null
server_received_at          timestamptz not null default now()
delivered_at                timestamptz null
read_at                     timestamptz null
is_deleted_global           boolean not null default false
deleted_global_at           timestamptz null
deleted_by_user_id          bigint null references users(id) on delete set null
expires_at                  timestamptz not null
auto_delete_after_read_seconds integer null
has_attachments             boolean not null default false
created_at                  timestamptz not null default now()
updated_at                  timestamptz not null default now()
```

### Индексы
```sql
index (conversation_id, created_at desc)
index (recipient_user_id, read_at)
index (sender_user_id, created_at desc)
index (expires_at)
index (is_deleted_global)
```

---

## 3.8 message_recipient_state
```sql
id                          bigserial primary key
message_id                  bigint not null references messages(id) on delete cascade
recipient_user_id           bigint not null references users(id) on delete cascade
recipient_device_id         bigint not null references devices(id) on delete cascade
delivery_status             varchar(32) not null default 'server_received'
delivered_at                timestamptz null
read_at                     timestamptz null
last_push_at                timestamptz null
failure_reason              text null
```

### Индексы
```sql
unique (message_id, recipient_device_id)
index (recipient_user_id, delivery_status)
index (read_at)
```

---

## 3.9 message_visibility_overrides
Для режима «удалить только у себя».

```sql
id                          bigserial primary key
message_id                  bigint not null references messages(id) on delete cascade
user_id                     bigint not null references users(id) on delete cascade
hidden_at                   timestamptz not null default now()
reason                      varchar(32) not null
```

### Индексы
```sql
unique (message_id, user_id)
index (user_id, hidden_at desc)
```

---

## 3.10 conversation_events
Также рекомендуется партиционирование по времени.

```sql
id                          bigserial primary key
event_uuid                  uuid not null unique
conversation_id             bigint not null references conversations(id) on delete cascade
actor_user_id               bigint not null references users(id) on delete cascade
actor_device_id             bigint null references devices(id) on delete set null
event_type                  varchar(64) not null
target_message_id           bigint null references messages(id) on delete set null
payload_encrypted           text null
created_at                  timestamptz not null default now()
```

### Индексы
```sql
index (conversation_id, id)
index (conversation_id, created_at)
index (event_type)
index (target_message_id)
```

---

## 3.11 attachments
```sql
id                          bigserial primary key
attachment_uuid             uuid not null unique
message_id                  bigint not null references messages(id) on delete cascade
storage_key                 text not null
bucket_name                 varchar(128) not null
encrypted_file_name         text null
encrypted_metadata          text null
file_size                   bigint not null
mime_hint                   varchar(255) null
sha256_encrypted_blob       varchar(64) not null
upload_status               varchar(32) not null default 'init'
created_at                  timestamptz not null default now()
expires_at                  timestamptz not null
deleted_at                  timestamptz null
```

### Индексы
```sql
index (message_id)
index (storage_key)
index (upload_status)
index (expires_at)
```

---

## 3.12 upload_sessions
```sql
id                          bigserial primary key
session_uuid                uuid not null unique
user_id                     bigint not null references users(id) on delete cascade
conversation_id             bigint not null references conversations(id) on delete cascade
status                      varchar(32) not null default 'init'
files_expected_count        integer not null
files_uploaded_count        integer not null default 0
created_at                  timestamptz not null default now()
expires_at                  timestamptz not null
completed_at                timestamptz null
```

### Ограничения
```sql
check (files_expected_count >= 1 and files_expected_count <= 20)
```

### Индексы
```sql
index (user_id, created_at desc)
index (conversation_id)
index (expires_at)
```

---

## 3.13 auth_email_codes
```sql
id                          bigserial primary key
user_id                     bigint not null references users(id) on delete cascade
code_hash                   text not null
purpose                     varchar(32) not null
attempts                    integer not null default 0
expires_at                  timestamptz not null
consumed_at                 timestamptz null
created_at                  timestamptz not null default now()
```

### Индексы
```sql
index (user_id, purpose)
index (expires_at)
```

---

## 3.14 login_attempts
```sql
id                          bigserial primary key
nickname                    varchar(64) not null
user_id                     bigint null references users(id) on delete set null
ip_address                  inet null
device_fingerprint          varchar(255) null
success                     boolean not null
failure_reason              varchar(128) null
created_at                  timestamptz not null default now()
```

### Индексы
```sql
index (nickname, created_at desc)
index (user_id, created_at desc)
index (ip_address, created_at desc)
```

---

## 3.15 account_deletion_queue
```sql
id                          bigserial primary key
user_id                     bigint not null references users(id) on delete cascade
scheduled_at                timestamptz not null
reason                      varchar(128) not null
executed_at                 timestamptz null
cancelled_at                timestamptz null
created_at                  timestamptz not null default now()
```

### Индексы
```sql
index (user_id)
index (scheduled_at)
index (executed_at)
```

---

# 4. Ключевые связи и правила

## 4.1 Пользователь и устройство
- Один пользователь имеет один активный девайс.
- При регистрации нового девайса старый девайс должен быть деактивирован или заменён по бизнес-правилу.

## 4.2 Чаты
- Между одной и той же парой пользователей может быть несколько записей `conversations`.
- Уникальность по паре пользователей не вводится.

## 4.3 Сообщения
- Все сообщения принадлежат конкретному `conversation_id`.
- Видимость для пользователя корректируется через `message_visibility_overrides`.
- Глобальное удаление отражается в `messages.is_deleted_global` и `conversation_events`.

## 4.4 Удаление аккаунта
При `purge`:
- conversations пользователя помечаются `is_purged = true`;
- связанные message rows переводятся в удалённое/очищенное состояние по принятой стратегии;
- attachments удаляются из MinIO;
- создаётся service event `chat_purged` для второго участника.

---

# 5. Redis: ключи и назначение

## 5.1 Presence
```text
presence:user:{user_id} -> online | offline
presence:device:{device_id} -> online | offline
presence:last_seen:{user_id} -> unix_ts
```

TTL обновляется heartbeat'ом.

## 5.2 WebSocket registry
```text
ws:user:{user_id} -> set(connection_id)
ws:device:{device_id} -> set(connection_id)
ws:conn:{connection_id} -> json(meta)
```

## 5.3 Pub/Sub channels
```text
channel:user:{user_id}:events
channel:device:{device_id}:events
channel:conversation:{conversation_id}
channel:push
```

Назначение:
- доставка событий между инстансами FastAPI;
- real-time fan-out;
- проброс событий о read/delete/clear.

## 5.4 Unread counters
```text
unread:user:{user_id}:conversation:{conversation_id} -> integer
unread:user:{user_id}:total -> integer
```

Redis — кэш/ускоритель, истина сверяется с PostgreSQL.

## 5.5 Email 2FA codes
```text
email2fa:user:{user_id}:{purpose} -> json(code_meta)
```

Поля:
- hash кода;
- expires_at;
- attempts;
- issued_at.

## 5.6 Lockout / anti-bruteforce state
```text
authfail:nickname:{nickname}
authfail:ip:{ip}
authfail:user:{user_id}
authlock:user:{user_id}
```

Даже если итоговое решение об удалении жёсткое, быстрый счётчик удобнее держать в Redis.

## 5.7 Distributed locks
```text
lock:conversation_clear:{conversation_id}
lock:message_delete:{message_id}
lock:upload_finalize:{session_uuid}
lock:account_purge:{user_id}
```

## 5.8 Idempotency
```text
idem:send:{idempotency_key}
idem:delete:{idempotency_key}
idem:clear:{idempotency_key}
```

## 5.9 Push batching / throttling
```text
push:pending:user:{user_id}
push:last_sent:user:{user_id}
```

---

# 6. MinIO model

## 6.1 Bucket strategy
Рекомендуемые бакеты:
- `chat-attachments-prod`
- `chat-temp-uploads-prod`

## 6.2 Object key format
Рекомендуемый ключ:

```text
attachments/{conversation_uuid}/{message_uuid}/{attachment_uuid}.bin
```

Для временных multipart uploads:

```text
temp/{upload_session_uuid}/{attachment_uuid}.part
```

## 6.3 Что хранится в объекте
- только зашифрованный blob файла;
- без plaintext имени файла;
- без открытых метаданных пользователя.

## 6.4 Что хранится в PostgreSQL рядом с объектом
- `storage_key`;
- `bucket_name`;
- `sha256_encrypted_blob`;
- encrypted metadata;
- file size;
- mime hint;
- attachment UUID;
- ссылка на message.

## 6.5 Доступ к скачиванию
Прямой публичный доступ запрещён.

Варианты:
1. короткоживущий presigned URL после проверки авторизации;
2. backend proxy download.

Для production чаще удобнее:
- upload через presigned URL;
- download тоже через короткий presigned URL или proxy для дополнительного контроля.

## 6.6 Удаление файлов
Файл должен удаляться, если:
- сообщение удалено глобально;
- чат очищен у обоих;
- аккаунт пользователя уничтожен;
- истёк срок хранения;
- upload session не была завершена.

Удаление выполняется worker'ом Celery.

---

# 7. Партиционирование PostgreSQL

## Рекомендуется партиционировать
- `messages`
- `conversation_events`
- при больших объёмах также `login_attempts`

## Критерий
По месяцу от `created_at` / `server_received_at`.

Пример логической схемы:
- `messages_2026_04`
- `messages_2026_05`
- `conversation_events_2026_04`

Это упростит cleanup и ускорит запросы по свежим данным.

---

# 8. Обязательные индексы верхнего уровня

## Users
```sql
users(nickname)
users(status)
```

## Conversations
```sql
conversations(user_a_id)
conversations(user_b_id)
conversations(updated_at desc)
```

## Messages
```sql
messages(conversation_id, created_at desc)
messages(recipient_user_id, read_at)
messages(expires_at)
messages(is_deleted_global)
```

## Events
```sql
conversation_events(conversation_id, id)
conversation_events(created_at)
```

## Visibility
```sql
message_visibility_overrides(user_id, message_id)
```

## Attachments
```sql
attachments(message_id)
attachments(upload_status)
attachments(expires_at)
```

---

# 9. Celery jobs, связанные с хранилищем

## 9.1 Message retention cleanup
- искать `messages.expires_at < now()`;
- удалять или переводить в expired state;
- публиковать service events;
- удалять связанные attachments.

## 9.2 Auto-delete after read
- искать messages, где есть `read_at` и `auto_delete_after_read_seconds`;
- пересчитывать момент удаления;
- выполнять удаление.

## 9.3 Upload session cleanup
- удалять незавершённые uploads;
- чистить временные объекты из `chat-temp-uploads-prod`.

## 9.4 Account purge
- деактивировать сессии;
- удалить prekeys и device state;
- пометить conversations как purged;
- удалить messages/files;
- разослать `chat_purged`.

---

# 10. Практические рекомендации по реализации

## Сообщения
- ciphertext допустимо хранить как `text` с base64 или как `bytea`.
- Для кросс-языкового API чаще проще `text/base64`.

## Ключи
- публичные ключи можно хранить как `text` в base64.
- все приватные ключи — только на устройстве.

## События
- клиент синхронизируется по `conversation_events.id`.
- это упрощает восстановление после reconnect.

## Удаление у себя
- не удалять физически строку message;
- использовать `message_visibility_overrides`.

## Удаление у всех
- использовать tombstone-подход и event.
- физическое удаление ciphertext можно выполнять асинхронно, если требуется.

---

# 11. Итоговая схема распределения данных

## PostgreSQL
- users
- devices
- prekeys
- sessions
- conversations
- messages
- message_recipient_state
- message_visibility_overrides
- conversation_events
- attachments
- upload_sessions
- auth_email_codes
- login_attempts
- account_deletion_queue

## Redis
- presence
- websocket registry
- pub/sub channels
- unread counters
- email2fa cache
- lockout cache
- distributed locks
- idempotency cache
- push throttling

## MinIO
- encrypted attachment blobs
- temp uploads

Это и есть полная production-модель хранения для данного проекта.
