import pytest

from core.config import normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # DO-style libpq URL: add async driver + translate sslmode -> ssl.
        (
            "postgresql://u:p@h:25060/db?sslmode=require",
            "postgresql+asyncpg://u:p@h:25060/db?ssl=require",
        ),
        # postgres:// short scheme is also rewritten; other sslmode values map 1:1.
        (
            "postgres://u:p@h/db?sslmode=verify-full",
            "postgresql+asyncpg://u:p@h/db?ssl=verify-full",
        ),
        # Already-correct async URL with no sslmode passes through untouched.
        (
            "postgresql+asyncpg://dsa:dsa@localhost:5432/dsa_test",
            "postgresql+asyncpg://dsa:dsa@localhost:5432/dsa_test",
        ),
        # Already using ssl= — left as-is.
        (
            "postgresql+asyncpg://u:p@h/db?ssl=require",
            "postgresql+asyncpg://u:p@h/db?ssl=require",
        ),
        # Bare scheme without query: just the driver suffix is added.
        (
            "postgresql://u:p@h/db",
            "postgresql+asyncpg://u:p@h/db",
        ),
    ],
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


def test_normalize_preserves_other_query_params() -> None:
    out = normalize_database_url("postgresql://u:p@h/db?sslmode=require&application_name=dsa")
    assert out.startswith("postgresql+asyncpg://u:p@h/db?")
    assert "ssl=require" in out
    assert "application_name=dsa" in out
    assert "sslmode" not in out
