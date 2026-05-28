import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from core.enums import AreaEnum

# Stable namespace UUID for deriving deterministic IDs from natural keys.
# Do not change — would break existing IDs.
DSA_NAMESPACE = uuid.UUID("1f4a2c8e-0d6b-4e3f-9a87-2c1b3d4f5e6a")


def derive_stable_id(name: str, dsc_name: str, designation_date: date) -> uuid.UUID:
    canonical = f"{name.strip().lower()}|{dsc_name.strip().lower()}|{designation_date.isoformat()}"
    return uuid.uuid5(DSA_NAMESPACE, canonical)


class ScrapedTrustedFlagger(BaseModel):
    """Result of fetch + parse + normalize from the EU source.

    Lacks operational fields (first_seen_at, last_seen_at, source_snapshot_url,
    status) which the ingest layer applies. URL/email fields are kept as plain
    strings here so malformed-but-real EU data doesn't blow up the parser;
    strict validation happens on the public TrustedFlagger contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    legal_form: str | None = None
    website: str | None = None
    email: str | None = None
    email_domain: str | None = None
    address_raw: str | None = None
    country_code: str = Field(min_length=2, max_length=2)
    city: str | None = None
    postal_code: str | None = None
    dsc_name: str | None = None
    dsc_country_code: str | None = Field(default=None, min_length=2, max_length=2)
    areas_of_expertise_raw: list[str] = Field(default_factory=list)
    areas_of_expertise: list[AreaEnum] = Field(default_factory=list)
    designation_date: date
    source_hash: str


class TrustedFlagger(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    legal_form: str | None = None
    website: HttpUrl | None = None
    email: EmailStr | None = None
    email_domain: str | None = None
    address_raw: str | None = None
    country_code: str = Field(min_length=2, max_length=2)
    city: str | None = None
    postal_code: str | None = None
    dsc_name: str | None = None
    dsc_country_code: str | None = Field(default=None, min_length=2, max_length=2)
    areas_of_expertise_raw: list[str] = Field(default_factory=list)
    areas_of_expertise: list[AreaEnum] = Field(default_factory=list)
    designation_date: date | None = None
    status: Literal["active", "suspended", "revoked"] = "active"
    first_seen_at: datetime
    last_seen_at: datetime
    source_hash: str
    source_snapshot_url: HttpUrl | None = None
