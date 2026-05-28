import json
from pathlib import Path

import pytest

from apps.scraper.parse import (
    ApiResponseError,
    HtmlStructureError,
    extract_api_url,
    normalize_rows,
    parse_api_response,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
EU_HTML = FIXTURE_DIR / "trusted_flaggers_eu.html"
EU_API_JSON = FIXTURE_DIR / "trusted_flaggers_api.json"


def test_extract_api_url_from_real_eu_html():
    url = extract_api_url(EU_HTML.read_text(encoding="utf-8"))
    assert url.startswith("https://webtools.europa.eu/")
    assert "/content" in url


def test_extract_api_url_accepts_bytes():
    url = extract_api_url(EU_HTML.read_bytes())
    assert url.startswith("https://")


def test_extract_api_url_raises_when_drupal_settings_missing():
    with pytest.raises(HtmlStructureError, match="drupal-settings-json"):
        extract_api_url("<html><body>no settings here</body></html>")


def test_extract_api_url_raises_on_malformed_json():
    bad = '<script data-drupal-selector="drupal-settings-json">{not json</script>'
    with pytest.raises(HtmlStructureError, match="not valid JSON"):
        extract_api_url(bad)


def test_extract_api_url_raises_when_cnt_description_url_missing():
    bad = '<script data-drupal-selector="drupal-settings-json">{"path": {}}</script>'
    with pytest.raises(HtmlStructureError, match="cnt_description"):
        extract_api_url(bad)


def test_parse_api_response_returns_data_list_from_real_fixture():
    payload = EU_API_JSON.read_bytes()
    rows = parse_api_response(payload)
    assert isinstance(rows, list)
    # As of 2026-05-28 the live register has 72 entries; this will grow over time,
    # so just assert non-trivial size rather than an exact count.
    assert len(rows) >= 60
    assert all(isinstance(r, dict) for r in rows)
    assert all("name" in r and "country_" in r for r in rows)


def test_parse_api_response_accepts_dict_input():
    payload = json.loads(EU_API_JSON.read_text(encoding="utf-8"))
    rows = parse_api_response(payload)
    assert len(rows) >= 60


def test_parse_api_response_raises_on_unsuccessful_wtstatus():
    with pytest.raises(ApiResponseError, match="wtstatus"):
        parse_api_response({"wtstatus": {"success": False, "status": "boom"}, "data": []})


def test_parse_api_response_raises_when_data_missing():
    with pytest.raises(ApiResponseError, match="data"):
        parse_api_response({"wtstatus": {"success": True}})


def test_parse_api_response_raises_on_non_dict():
    with pytest.raises(ApiResponseError, match="expected dict"):
        parse_api_response("[1, 2, 3]")


def test_full_pipeline_against_real_fixture():
    """End-to-end against the captured EU snapshot: parse → normalize → no fatal errors."""
    rows = parse_api_response(EU_API_JSON.read_bytes())
    normalized, errors = normalize_rows(rows)
    assert not errors, f"normalization errors against live fixture: {errors[:3]}"
    assert len(normalized) == len(rows)
    countries = {tf.country_code for tf in normalized}
    assert (
        "SK" in countries or "DE" in countries or "FR" in countries
    ), "real EU data should cover several countries"
    # Every row must have at least one area mapped (other is allowed as fallback).
    assert all(tf.areas_of_expertise for tf in normalized)
