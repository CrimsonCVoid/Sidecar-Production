"""FastAPI dependency injection: settings singleton and Supabase client."""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Depends
from supabase import Client, create_client

from .config import Settings

log = logging.getLogger(__name__)


@lru_cache
def get_settings() -> Settings:
    """Return the application settings singleton.

    Uses ``@lru_cache`` so the Settings object (and the .env file read)
    happens exactly once per process.
    """
    return Settings()


def get_supabase(settings: Settings = Depends(get_settings)) -> Client:
    """Create a Supabase client using the service-role key.

    The client is constructed on each call because the ``Depends()`` chain
    is evaluated per-request.  The underlying HTTP connection pool in httpx
    handles connection reuse automatically.
    """
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
