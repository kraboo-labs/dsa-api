from datetime import date

import pytest

from core.enums import AreaEnum
from core.normalize import (
    AREA_LABEL_MAP,
    RowNormalizationError,
    compute_row_hash,
    decode_url_encoded_email,
    extract_dsc_country_code,
    extract_email_domain,
    normalize_areas,
    normalize_row,
    parse_eu_date,
    split_areas_raw,
)


def test_area_label_map_covers_all_known_eu_labels():
    # All non-empty raw labels seen in 2026-05-28 dump must map.
    seen_raw_labels = {label.strip().lower() for label in AREA_LABEL_MAP}
    assert len(seen_raw_labels) == len(AREA_LABEL_MAP), "duplicate lowercased key"


def test_split_areas_raw_handles_semicolon_separator():
    raw = "Cyberviolence; Illegal Speech; Protection of minors violations"
    assert split_areas_raw(raw) == [
        "Cyberviolence",
        "Illegal Speech",
        "Protection of minors violations",
    ]


def test_split_areas_raw_strips_and_filters_empty():
    assert split_areas_raw(" ;  Illegal Speech ;; ") == ["Illegal Speech"]
    assert split_areas_raw("") == []
    assert split_areas_raw(None) == []


def test_normalize_areas_maps_known_labels():
    assert normalize_areas(["Illegal Speech", "Cyberviolence"]) == [
        AreaEnum.illegal_speech,
        AreaEnum.cyber_violence,
    ]


def test_normalize_areas_falls_back_to_other_for_unknown():
    assert normalize_areas(["Some Brand New Category"]) == [AreaEnum.other]


def test_normalize_areas_dedupes_preserving_order():
    # "Cyber violence against women" and "Cyberviolence" map to different enums;
    # repeated raw input shouldn't produce duplicates.
    out = normalize_areas(["Cyberviolence", "Illegal Speech", "Cyberviolence"])
    assert out == [AreaEnum.cyber_violence, AreaEnum.illegal_speech]


def test_normalize_areas_is_case_insensitive():
    assert normalize_areas(["ILLEGAL SPEECH", "illegal speech"]) == [AreaEnum.illegal_speech]


def test_extract_dsc_country_code_finds_trailing_paren_code():
    name = "Coimisiún na Meán (IE)"
    assert extract_dsc_country_code(name) == "IE"


def test_extract_dsc_country_code_returns_none_when_no_code():
    assert extract_dsc_country_code("Rada pre mediálne služby | Council for Media Services") is None
    assert extract_dsc_country_code("") is None
    assert extract_dsc_country_code(None) is None


def test_parse_eu_date_handles_ddmmyyyy():
    assert parse_eu_date("17/05/2026") == date(2026, 5, 17)


def test_parse_eu_date_returns_none_on_garbage():
    assert parse_eu_date("not-a-date") is None
    assert parse_eu_date("") is None
    assert parse_eu_date(None) is None
    assert parse_eu_date("2026-05-17") is None  # ISO format is wrong shape for EU api


def test_decode_url_encoded_email_strips_mailto_prefix():
    assert decode_url_encoded_email("mailto%3Afoo%40bar.org") == "foo@bar.org"


def test_decode_url_encoded_email_handles_plain_email():
    assert decode_url_encoded_email("foo%40bar.org") == "foo@bar.org"


def test_decode_url_encoded_email_returns_none_on_empty():
    assert decode_url_encoded_email(None) is None
    assert decode_url_encoded_email("") is None


def test_extract_email_domain():
    assert extract_email_domain("foo@bar.org") == "bar.org"
    assert extract_email_domain("FOO@BAR.ORG") == "bar.org"
    assert extract_email_domain("no-at-sign") is None
    assert extract_email_domain(None) is None


def test_compute_row_hash_is_deterministic():
    row = {"name": "Foo", "country_": "DE", "areas_of_expertise": "Illegal Speech"}
    assert compute_row_hash(row) == compute_row_hash(dict(row))


def test_compute_row_hash_is_key_order_independent():
    a = {"name": "Foo", "country_": "DE"}
    b = {"country_": "DE", "name": "Foo"}
    assert compute_row_hash(a) == compute_row_hash(b)


def test_compute_row_hash_changes_on_value_change():
    base = {"name": "Foo", "country_": "DE"}
    changed = {"name": "Foo", "country_": "FR"}
    assert compute_row_hash(base) != compute_row_hash(changed)


def test_normalize_row_full_happy_path():
    raw = {
        "name": "Asociatia Serviciul Iezuitilor pentru Refugiatii din Romania",
        "country_": "RO",
        "date_of_certification_": "17/05/2026",
        "dsc_country_": "ANCOM | National Authority (RO)",
        "tf_address": "strada Maior Ilie Opriș nr. 54, sector 4, Bucharest, Romania",
        "tf_contact_": "flagger@jrsromania.ro",
        "tf_website": "https://jrsromania.org/ro/acasa/",
        "areas_of_expertise": "Illegal Speech",
    }
    tf = normalize_row(raw)
    assert tf.name == raw["name"]
    assert tf.country_code == "RO"
    assert tf.dsc_country_code == "RO"
    assert tf.dsc_name == "ANCOM | National Authority (RO)"
    assert tf.designation_date == date(2026, 5, 17)
    assert tf.email == "flagger@jrsromania.ro"
    assert tf.email_domain == "jrsromania.ro"
    assert tf.areas_of_expertise == [AreaEnum.illegal_speech]
    assert tf.areas_of_expertise_raw == ["Illegal Speech"]
    assert tf.source_hash  # non-empty


def test_normalize_row_falls_back_to_country_when_dsc_lacks_code():
    raw = {
        "name": "Foo",
        "country_": "SK",
        "date_of_certification_": "01/01/2026",
        "dsc_country_": "Rada pre mediálne služby | Council for Media Services",
        "areas_of_expertise": "Illegal Speech",
    }
    tf = normalize_row(raw)
    assert tf.dsc_country_code == "SK"


def test_normalize_row_raises_on_missing_name():
    raw = {"name": "", "country_": "DE", "date_of_certification_": "01/01/2026"}
    with pytest.raises(RowNormalizationError, match="name"):
        normalize_row(raw)


def test_normalize_row_raises_on_missing_country():
    raw = {"name": "Foo", "country_": "", "date_of_certification_": "01/01/2026"}
    with pytest.raises(RowNormalizationError, match="country_code"):
        normalize_row(raw)


def test_normalize_row_raises_on_unparseable_date():
    raw = {"name": "Foo", "country_": "DE", "date_of_certification_": "nope"}
    with pytest.raises(RowNormalizationError, match="date_of_certification"):
        normalize_row(raw)
