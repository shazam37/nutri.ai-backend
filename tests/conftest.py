"""
tests/conftest.py
─────────────────
Shared fixtures and configuration for all test modules.
Uses pytest + httpx AsyncClient against a running server.

Run all tests:
  pytest tests/ -v

Run a specific module:
  pytest tests/test_auth.py -v

Run with output (see print statements):
  pytest tests/ -v -s

Environment:
  Set TEST_BASE_URL to point at your server (default: localhost:8000)
  Tests are stateful — they run in order and share state via conftest fixtures.
  Each full test run signs up a fresh user so tests never conflict.
"""

import os
import pytest
import httpx
import asyncio

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
API      = f"{BASE_URL}/api/v1"

# Unique email per test run so re-runs don't clash
import time
TEST_EMAIL    = f"testuser_{int(time.time())}@nutriai.com"
TEST_PASSWORD = "testpass123"
TEST_NAME     = "Test User"


# ─────────────────────────────────────────────
# Shared state — passed between test modules
# ─────────────────────────────────────────────

class State:
    """
    Holds test session state.
    Populated incrementally as tests run.
    Add new fields here when adding new feature tests.
    """
    access_token:   str  = ""
    refresh_token:  str  = ""
    user_id:        str  = ""
    banana_log_id:  str  = ""
    lunch_log_id:   str  = ""
    pizza_log_id:   str  = ""
    plan_id:        str  = ""
    egg_item_id:    str  = ""
    spinach_item_id: str = ""


state = State()


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def shared_state():
    """Single State object shared across all test modules in a session."""
    return state


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api_url():
    return API


@pytest.fixture(scope="session")
def client():
    """Synchronous httpx client — reused across entire test session."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        yield c


def auth_headers(token: str) -> dict:
    """Helper — build Authorization header from token string."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def headers(shared_state):
    """
    Returns a callable that always uses the current access token.
    Use as: headers() inside tests to get fresh headers.
    """
    def _headers():
        return auth_headers(shared_state.access_token)
    return _headers