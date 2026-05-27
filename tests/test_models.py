from datetime import UTC, date, datetime

from core.enums import AreaEnum
from core.models import TrustedFlagger, derive_stable_id


def test_derive_stable_id_is_deterministic():
    id_a = derive_stable_id("Foo NGO", "Coimisiún na Meán", date(2025, 1, 15))
    id_b = derive_stable_id("Foo NGO", "Coimisiún na Meán", date(2025, 1, 15))
    assert id_a == id_b


def test_derive_stable_id_normalizes_whitespace_and_case():
    id_a = derive_stable_id("Foo NGO", "Coimisiún na Meán", date(2025, 1, 15))
    id_b = derive_stable_id("  foo ngo  ", "COIMISIÚN NA MEÁN", date(2025, 1, 15))
    assert id_a == id_b


def test_derive_stable_id_differs_by_date():
    id_a = derive_stable_id("Foo NGO", "DSC X", date(2025, 1, 15))
    id_b = derive_stable_id("Foo NGO", "DSC X", date(2025, 1, 16))
    assert id_a != id_b


def test_derive_stable_id_differs_by_dsc():
    id_a = derive_stable_id("Foo NGO", "DSC X", date(2025, 1, 15))
    id_b = derive_stable_id("Foo NGO", "DSC Y", date(2025, 1, 15))
    assert id_a != id_b


def test_trusted_flagger_minimal_construction():
    now = datetime.now(UTC)
    tf = TrustedFlagger(
        id=derive_stable_id("Foo NGO", "DSC X", date(2025, 1, 15)),
        name="Foo NGO",
        country_code="DE",
        areas_of_expertise=[AreaEnum.ip_infringement],
        first_seen_at=now,
        last_seen_at=now,
        source_hash="abc123",
    )
    assert tf.name == "Foo NGO"
    assert tf.status == "active"
    assert AreaEnum.ip_infringement in tf.areas_of_expertise
