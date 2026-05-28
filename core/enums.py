from enum import StrEnum


class AreaEnum(StrEnum):
    # PRD §5 baseline taxonomy
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
    # Added 2026-05-28 after taxonomy mapping pass against real EU data (PRD Open Question §14.5).
    # All six appear in the live register and don't map cleanly to the baseline.
    data_privacy = "data_privacy"
    public_security = "public_security"
    violence = "violence"
    self_harm = "self_harm"
    animal_welfare = "animal_welfare"
    civil_discourse = "civil_discourse"
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
