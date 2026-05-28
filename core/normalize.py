import hashlib
import json
import re
import urllib.parse
from datetime import date, datetime
from typing import Any

from core.enums import AreaEnum
from core.models import ScrapedTrustedFlagger, derive_stable_id

# Mapping from EU's free-text area labels (lowercased) to normalized AreaEnum.
# Captured 2026-05-28 from live data (PRD Open Question §14.5).
# Unknown labels fall back to AreaEnum.other; raw label is preserved alongside.
AREA_LABEL_MAP: dict[str, AreaEnum] = {
    "intellectual property infringements": AreaEnum.ip_infringement,
    "illegal speech": AreaEnum.illegal_speech,
    "terrorist content": AreaEnum.terrorist_content,
    "csam": AreaEnum.csam,
    "protection of minors violations": AreaEnum.protection_of_minors,
    "cyberviolence": AreaEnum.cyber_violence,
    "cyber violence against women": AreaEnum.gender_based_violence,
    "scams and fraud": AreaEnum.scams_fraud,
    "illegal products": AreaEnum.illegal_products,
    "consumer protection": AreaEnum.consumer_protection,
    "consumer information infringements": AreaEnum.consumer_protection,
    "disinformation": AreaEnum.disinformation,
    "data protection and privacy violations": AreaEnum.data_privacy,
    "risk for public security": AreaEnum.public_security,
    "violence": AreaEnum.violence,
    "incitement to self-harm": AreaEnum.self_harm,
    "animal welfare": AreaEnum.animal_welfare,
    "negative effects on civil discourse and elections": AreaEnum.civil_discourse,
}

_DSC_COUNTRY_RE = re.compile(r"\(([A-Z]{2})\)\s*$")


def split_areas_raw(raw: str | None) -> list[str]:
    """EU API returns areas as '; '-separated single string. Splits and trims."""
    if not raw:
        return []
    return [p.strip() for p in raw.split(";") if p.strip()]


def normalize_areas(raw_labels: list[str]) -> list[AreaEnum]:
    """Map raw labels to AreaEnum, deduped, preserving first-seen order."""
    seen: dict[AreaEnum, None] = {}
    for label in raw_labels:
        mapped = AREA_LABEL_MAP.get(label.strip().lower(), AreaEnum.other)
        seen.setdefault(mapped, None)
    return list(seen.keys())


def extract_dsc_country_code(dsc_name: str | None) -> str | None:
    """Pull the trailing '(CC)' country code from a DSC name string."""
    if not dsc_name:
        return None
    match = _DSC_COUNTRY_RE.search(dsc_name)
    return match.group(1) if match else None


def parse_eu_date(raw: str | None) -> date | None:
    """EU API uses DD/MM/YYYY. Returns None on missing/invalid."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def decode_url_encoded_email(encoded: str | None) -> str | None:
    """tf_contact__url is URL-encoded 'mailto:...'. Returns bare email or None."""
    if not encoded:
        return None
    decoded = urllib.parse.unquote(encoded)
    if decoded.startswith("mailto:"):
        decoded = decoded[len("mailto:") :]
    return decoded.strip() or None


def extract_email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.split("@", 1)[1].strip().lower()
    return domain or None


def compute_row_hash(raw: dict[str, Any]) -> str:
    """SHA-256 over a canonical JSON of the raw row. Stable across scrapes."""
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RowNormalizationError(ValueError):
    """Raised when a raw EU row is missing fields required by ScrapedTrustedFlagger."""


def normalize_row(raw: dict[str, Any]) -> ScrapedTrustedFlagger:
    """Map a raw EU JSON-API row to ScrapedTrustedFlagger.

    Raises RowNormalizationError if name / country / designation_date are missing
    or unparseable — those are mandatory for a stable identity.
    """
    name = (raw.get("name") or "").strip()
    country_code = (raw.get("country_") or "").strip().upper()
    if not name:
        raise RowNormalizationError(f"row missing required 'name': {raw}")
    if len(country_code) != 2:
        raise RowNormalizationError(f"row has invalid country_code {country_code!r}: {raw}")

    designation_date = parse_eu_date(raw.get("date_of_certification_"))
    if designation_date is None:
        raise RowNormalizationError(
            f"row has unparseable 'date_of_certification_'={raw.get('date_of_certification_')!r}"
        )

    dsc_name = (raw.get("dsc_country_") or "").strip() or None
    dsc_country_code = extract_dsc_country_code(dsc_name) or country_code

    areas_raw = split_areas_raw(raw.get("areas_of_expertise"))
    areas = normalize_areas(areas_raw)

    email = (raw.get("tf_contact_") or "").strip() or None
    if email is None:
        email = decode_url_encoded_email(raw.get("tf_contact__url"))

    website = (raw.get("tf_website") or "").strip() or None
    address_raw = (raw.get("tf_address") or "").strip() or None

    return ScrapedTrustedFlagger(
        id=derive_stable_id(name, dsc_name or "", designation_date),
        name=name,
        website=website,
        email=email,
        email_domain=extract_email_domain(email),
        address_raw=address_raw,
        country_code=country_code,
        dsc_name=dsc_name,
        dsc_country_code=dsc_country_code,
        areas_of_expertise_raw=areas_raw,
        areas_of_expertise=areas,
        designation_date=designation_date,
        source_hash=compute_row_hash(raw),
    )
