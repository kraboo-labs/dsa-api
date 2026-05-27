from enum import StrEnum


class AreaEnum(StrEnum):
    ip_infringement = "ip_infringement"
    illegal_speech = "illegal_speech"
    terrorist_content = "terrorist_content"
    csam = "csam"
    protection_of_minors = "protection_of_minors"
    cyber_violence = "cyber_violence"
    gender_based_violence = "gender_based_violence"
    scams_fraud = "scams_fraud"
    illegal_products = "illegal_products"
    consumer_protection = "consumer_protection"
    disinformation = "disinformation"
    other = "other"


class TFStatus(StrEnum):
    active = "active"
    suspended = "suspended"
    revoked = "revoked"


class EventType(StrEnum):
    created = "created"
    updated = "updated"
    removed = "removed"
    restored = "restored"


class ScrapeRunStatus(StrEnum):
    running = "running"
    success = "success"
    failed = "failed"
    partial = "partial"
