from enum import StrEnum


class ProtectionMode(StrEnum):
    NORMAL = "normal"
    SHARED_SECRET = "shared_secret"


class MessageType(StrEnum):
    TEXT = "text"
    FILE = "file"
    SERVICE = "service"


class EncryptionMode(StrEnum):
    SIGNAL = "signal"
    SIGNAL_PLUS_SHARED_SECRET = "signal_plus_shared_secret"


class DeliveryStatus(StrEnum):
    SERVER_RECEIVED = "server_received"
    PUSHED = "pushed"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    DELETED_GLOBAL = "deleted_global"
    EXPIRED = "expired"
    PURGED = "purged"


class VisibilityReason(StrEnum):
    USER_DELETED = "user_deleted"
    CONVERSATION_CLEARED_LOCAL = "conversation_cleared_local"


class EventType(StrEnum):
    MESSAGE_CREATED = "message_created"
    MESSAGE_DELETED_GLOBAL = "message_deleted_global"
    MESSAGE_HIDDEN_FOR_USER = "message_hidden_for_user"
    CONVERSATION_CLEARED_LOCAL = "conversation_cleared_local"
    CONVERSATION_CLEARED_GLOBAL = "conversation_cleared_global"
    MESSAGE_DELIVERED = "message_delivered"
    MESSAGE_READ = "message_read"
    MESSAGE_REACTION_SET = "message_reaction_set"
    MESSAGE_REACTION_REMOVED = "message_reaction_removed"
    CONVERSATION_SETTINGS_UPDATED = "conversation_settings_updated"
    FILE_UPLOADED = "file_uploaded"
    FILE_DELETED = "file_deleted"
    PARTICIPANT_KEY_CHANGED = "participant_key_changed"
    CONVERSATION_PURGED = "conversation_purged"


class AttachmentStatus(StrEnum):
    INIT = "init"
    UPLOADED = "uploaded"
    LINKED = "linked"
    DELETED = "deleted"


class UploadSessionStatus(StrEnum):
    INIT = "init"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ABORTED = "aborted"
