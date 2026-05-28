import asyncio
import hashlib
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    body: bytes
    content_hash: str  # sha256 hex


class FetchError(RuntimeError):
    """Raised when fetch fails after all retry attempts."""


async def fetch(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    user_agent: str = "dsa-api-scraper/0.1 (+https://dsa-api.com)",
    timeout: float = 30.0,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> FetchResult:
    """GET `url` with exponential backoff. Caller owns the client unless omitted.

    Retries on transport errors, timeouts, and 5xx. 4xx is treated as a hard
    failure (the URL is wrong; retrying won't help).
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.get(url, headers={"User-Agent": user_agent})
                if 500 <= response.status_code < 600:
                    raise httpx.HTTPStatusError(
                        f"server error {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                body = response.content
                return FetchResult(
                    url=str(response.url),
                    status_code=response.status_code,
                    body=body,
                    content_hash=hashlib.sha256(body).hexdigest(),
                )
            except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_err = e
                # Don't retry client errors (4xx) — they're not transient.
                if isinstance(e, httpx.HTTPStatusError) and 400 <= e.response.status_code < 500:
                    raise FetchError(f"client error {e.response.status_code} fetching {url}") from e
                if attempt < max_attempts:
                    await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))
        raise FetchError(f"failed after {max_attempts} attempts: {last_err}") from last_err
    finally:
        if own_client:
            await client.aclose()
