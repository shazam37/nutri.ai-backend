"""
tests/test_01_auth.py
─────────────────────
Tests: signup, login, token refresh, /me endpoint
Runs first — populates state.access_token, state.user_id etc.
for all subsequent test modules.

Adding new auth tests:
  - Add a new test_ function below
  - Use shared_state to read/write session tokens
  - Prefix with test_01_XX to control run order within this module
"""

import pytest
from tests.conftest import API, TEST_EMAIL, TEST_PASSWORD, TEST_NAME


SIGNUP_PAYLOAD = {
    "email":                TEST_EMAIL,
    "password":             TEST_PASSWORD,
    "name":                 TEST_NAME,
    "age":                  25,
    "weight_kg":            70.0,
    "height_cm":            175.0,
    "gender":               "male",
    "goal":                 "lose_weight",
    "activity_level":       "moderate",
    "dietary_restrictions": [],
}


class TestAuth:

    def test_01_signup(self, client, shared_state):
        """Signup creates user and returns tokens + calculated macro targets."""
        resp = client.post(f"{API}/auth/signup", json=SIGNUP_PAYLOAD)

        assert resp.status_code == 201, f"Signup failed: {resp.text}"
        data = resp.json()

        # Required fields
        assert "user_id"       in data
        assert "access_token"  in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

        # Targets should be calculated
        targets = data["targets"]
        assert targets["calories"]  > 0
        assert targets["protein_g"] > 0
        assert targets["carbs_g"]   > 0
        assert targets["fat_g"]     > 0

        # Persist for other tests
        shared_state.access_token  = data["access_token"]
        shared_state.refresh_token = data["refresh_token"]
        shared_state.user_id       = data["user_id"]

        print(f"\n  ✓ User created: {data['user_id']}")
        print(f"  ✓ Calorie target: {targets['calories']} kcal")


    def test_02_signup_duplicate_email_rejected(self, client, shared_state):
        """Signing up with an existing email returns 400."""
        resp = client.post(f"{API}/auth/signup", json=SIGNUP_PAYLOAD)
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()


    def test_03_login_valid(self, client, shared_state):
        """Login with correct credentials returns new tokens."""
        resp = client.post(f"{API}/auth/login", json={
            "email":    TEST_EMAIL,
            "password": TEST_PASSWORD,
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        data = resp.json()

        assert "access_token"  in data
        assert "refresh_token" in data
        assert data["user_id"] == shared_state.user_id

        # Update tokens to freshest ones
        shared_state.access_token  = data["access_token"]
        shared_state.refresh_token = data["refresh_token"]


    def test_04_login_wrong_password(self, client):
        """Login with wrong password returns 401."""
        resp = client.post(f"{API}/auth/login", json={
            "email":    TEST_EMAIL,
            "password": "wrongpassword",
        })
        assert resp.status_code == 401


    def test_05_login_unknown_email(self, client):
        """Login with unknown email returns 401."""
        resp = client.post(f"{API}/auth/login", json={
            "email":    "nobody@nutriai.com",
            "password": "whatever",
        })
        assert resp.status_code == 401


    def test_06_get_me(self, client, shared_state):
        """GET /auth/me returns current user profile from token."""
        resp = client.get(
            f"{API}/auth/me",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200, f"/me failed: {resp.text}"
        data = resp.json()

        assert data["user_id"] == shared_state.user_id
        assert data["email"]   == TEST_EMAIL
        assert data["name"]    == TEST_NAME
        assert "targets"       in data
        assert data["goal"]    == "lose_weight"


    def test_07_get_me_no_token(self, client):
        """GET /auth/me without token returns 401."""
        resp = client.get(f"{API}/auth/me")
        assert resp.status_code == 401


    def test_08_get_me_bad_token(self, client):
        """GET /auth/me with garbage token returns 401."""
        resp = client.get(
            f"{API}/auth/me",
            headers={"Authorization": "Bearer notavalidtoken"}
        )
        assert resp.status_code == 401


    def test_09_refresh_token(self, client, shared_state):
        """Refresh token returns a new valid access token."""
        resp = client.post(f"{API}/auth/refresh", json={
            "refresh_token": shared_state.refresh_token
        })
        assert resp.status_code == 200, f"Refresh failed: {resp.text}"
        data = resp.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # New token should be different from the old one
        old_token = shared_state.access_token
        shared_state.access_token = data["access_token"]
        # Note: tokens can technically be identical if issued within same second
        # so we just verify it works, not that it differs
        print(f"\n  ✓ Token refreshed successfully")


    def test_10_refresh_invalid_token(self, client):
        """Refresh with an invalid token returns 401."""
        resp = client.post(f"{API}/auth/refresh", json={
            "refresh_token": "invalid.token.here"
        })
        assert resp.status_code == 401