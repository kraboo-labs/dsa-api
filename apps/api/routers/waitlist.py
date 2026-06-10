import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/waitlist", tags=["waitlist"])

RESEND_API_URL = "https://api.resend.com"

CONFIRMATION_SUBJECT = "You're on the dsa-api Pro waitlist"
CONFIRMATION_BODY = (
    "Thanks for your interest in the dsa-api Pro tier (webhooks, point-in-time "
    "audit, SLA).\n\n"
    "We'll write to this address when Pro opens — and only then. The free API "
    "and the CC-BY open dataset stay free either way.\n\n"
    "https://dsa-api.com\n"
)


class WaitlistSignup(BaseModel):
    email: EmailStr


async def subscribe(
    email: str,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
) -> bool:
    """Add an email to the Resend waitlist audience.

    Returns True when the contact was created or already existed (signup is
    idempotent from the caller's perspective). Returns False on any other
    Resend failure — the caller decides how to surface it. When
    ``resend_from`` is set, a confirmation email is sent best-effort: a
    delivery failure never fails the signup itself.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout)
    headers = {"Authorization": f"Bearer {settings.resend_api_key}"}
    try:
        response = await client.post(
            f"{RESEND_API_URL}/audiences/{settings.resend_audience_id}/contacts",
            headers=headers,
            json={"email": email, "unsubscribed": False},
        )
        # 409 = contact already in the audience: fine, they're on the list.
        if response.status_code not in (200, 201, 409):
            logger.error("resend contact create failed: HTTP %s", response.status_code)
            return False

        if settings.resend_from:
            try:
                confirm = await client.post(
                    f"{RESEND_API_URL}/emails",
                    headers=headers,
                    json={
                        "from": settings.resend_from,
                        "to": [email],
                        "subject": CONFIRMATION_SUBJECT,
                        "text": CONFIRMATION_BODY,
                    },
                )
                if confirm.status_code != 200:
                    logger.warning("resend confirmation send failed: HTTP %s", confirm.status_code)
            except httpx.HTTPError:
                logger.warning("resend confirmation send failed", exc_info=True)
        return True
    except httpx.HTTPError:
        logger.error("resend request failed", exc_info=True)
        return False
    finally:
        if own_client:
            await client.aclose()


@router.post("", status_code=202)
async def join_waitlist(
    payload: WaitlistSignup,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if not (settings.resend_api_key and settings.resend_audience_id):
        # Feature is off, not broken — 404 keeps uptime monitors quiet.
        raise HTTPException(status_code=404, detail="waitlist is not enabled")
    if not await subscribe(payload.email, settings):
        raise HTTPException(status_code=502, detail="waitlist signup failed, try again later")
    return {"status": "subscribed"}
