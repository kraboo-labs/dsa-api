"""POST /v1/waitlist — capture Pro/Business interest into a Resend audience.

Demand validation for the paid tiers. When Resend is configured, the submitted
email is added as a contact in the configured audience. Unconfigured → 503, so
the frontend can degrade gracefully.
"""

import re
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.config import Settings, get_settings

router = APIRouter(prefix="/v1/waitlist", tags=["waitlist"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WaitlistIn(BaseModel):
    email: str
    # Honeypot: a hidden field real users never fill. Bots often do.
    company: str | None = None


def _clean_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="invalid email")
    return email


async def _resend_add_contact(settings: Settings, email: str) -> None:
    """Add a contact to the Resend audience. Idempotent for existing contacts."""
    url = f"https://api.resend.com/audiences/{settings.resend_audience_id}/contacts"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"email": email, "unsubscribed": False},
        )
    # 200/201 created, 409 already-exists → success. Auth/5xx → surface as 502.
    if resp.status_code in (401, 403) or resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="waitlist provider unavailable")


@router.post("", status_code=202)
async def join_waitlist(
    body: WaitlistIn,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    if not (settings.resend_api_key and settings.resend_audience_id):
        raise HTTPException(status_code=503, detail="waitlist not configured")
    email = _clean_email(body.email)
    if body.company:  # honeypot tripped — accept silently, don't store
        return {"ok": True, "status": "subscribed"}
    await _resend_add_contact(settings, email)
    return {"ok": True, "status": "subscribed"}
