import json
import re
from typing import Any

from core.models import ScrapedTrustedFlagger
from core.normalize import RowNormalizationError, normalize_row

# The EU page injects its Drupal settings as a JSON blob inside a <script type="application/json">
# tag. The trusted-flagger JSON API URL lives under settings.cnt_description.url.
_DRUPAL_SETTINGS_RE = re.compile(
    r'<script[^>]*data-drupal-selector="drupal-settings-json"[^>]*>([^<]+)</script>',
    re.DOTALL,
)


class HtmlStructureError(ValueError):
    """Raised when the EU HTML doesn't contain the expected drupal settings blob.

    PRD §11 calls for failing loudly on structure change rather than writing
    bad data — alert + abort run, do not modify trusted_flaggers table.
    """


class ApiResponseError(ValueError):
    """Raised when the JSON API response doesn't have the expected envelope."""


def extract_api_url(html: str | bytes) -> str:
    """Pull the JSON data API URL out of the EU page's drupal-settings-json blob."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    match = _DRUPAL_SETTINGS_RE.search(html)
    if not match:
        raise HtmlStructureError("drupal-settings-json script tag not found")
    try:
        settings = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise HtmlStructureError(f"drupal-settings-json is not valid JSON: {e}") from e
    try:
        url = settings["cnt_description"]["url"]
    except (KeyError, TypeError) as e:
        raise HtmlStructureError(f"cnt_description.url missing from drupal settings: {e}") from e
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise HtmlStructureError(f"cnt_description.url is not a usable URL: {url!r}")
    return url


def parse_api_response(payload: bytes | str | dict[str, Any]) -> list[dict[str, Any]]:
    """Decode the JSON envelope and return the raw row list. Does not normalize."""
    data = json.loads(payload) if isinstance(payload, bytes | str) else payload
    if not isinstance(data, dict):
        raise ApiResponseError(f"expected dict response, got {type(data).__name__}")
    status = data.get("wtstatus")
    if isinstance(status, dict) and status.get("success") is False:
        raise ApiResponseError(f"API returned wtstatus.success=false: {status}")
    rows = data.get("data")
    if not isinstance(rows, list):
        raise ApiResponseError("API response missing 'data' list")
    return rows


def normalize_rows(rows: list[dict[str, Any]]) -> tuple[list[ScrapedTrustedFlagger], list[str]]:
    """Normalize raw rows; return (normalized, errors). Bad rows are skipped, not fatal."""
    normalized: list[ScrapedTrustedFlagger] = []
    errors: list[str] = []
    for raw in rows:
        try:
            normalized.append(normalize_row(raw))
        except RowNormalizationError as e:
            errors.append(str(e))
    return normalized, errors
