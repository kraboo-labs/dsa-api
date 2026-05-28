import os

# Settings() requires DSA_DATABASE_URL and DSA_REDIS_URL. Provide harmless defaults
# so tests can import the app without a real .env. Dependency overrides keep tests
# from actually opening these connections.
os.environ.setdefault("DSA_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("DSA_REDIS_URL", "redis://localhost:6379/0")
