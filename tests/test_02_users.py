"""
tests/test_02_users.py
──────────────────────
Tests: GET profile, PUT profile updates, macro recalculation on body stat change.

Adding new user tests:
  - Add test_ functions to the TestUsers class
  - shared_state.user_id is always available after test_01_auth runs
"""

import pytest
from tests.conftest import API


class TestUsers:

    def test_01_get_profile(self, client, shared_state):
        """GET /users/{id} returns full user profile."""
        resp = client.get(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200, f"Get profile failed: {resp.text}"
        data = resp.json()

        assert data["user_id"]   == shared_state.user_id
        assert data["age"]       == 25
        assert data["weight_kg"] == 70.0
        assert data["height_cm"] == 175.0
        assert "targets"         in data
        assert data["targets"]["calories"] > 0


    def test_02_get_profile_wrong_user(self, client, shared_state):
        """GET /users/{id} for another user returns 403."""
        resp = client.get(
            f"{API}/users/nonexistent-user-id",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        # Either 404 (not found) or 403 (not authorised) — both are acceptable
        assert resp.status_code in (403, 404)


    def test_03_update_name(self, client, shared_state):
        """PUT /users/{id} can update name without affecting targets."""
        resp = client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"name": "Updated User"}
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] is True

        # Verify name changed
        profile = client.get(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        assert profile["name"] == "Updated User"


    def test_04_update_weight_recalculates_targets(self, client, shared_state):
        """Changing weight_kg triggers automatic macro recalculation."""
        original = client.get(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        original_calories = original["targets"]["calories"]

        # Reduce weight significantly — should lower calorie target
        resp = client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"weight_kg": 60.0}
        )
        assert resp.status_code == 200
        new_calories = resp.json()["targets"]["calories"]

        # Lighter person = lower target
        assert new_calories < original_calories
        print(f"\n  ✓ Targets recalculated: {original_calories} → {new_calories} kcal")

        # Restore weight for other tests
        client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"weight_kg": 70.0}
        )


    def test_05_update_goal_changes_targets(self, client, shared_state):
        """Switching goal from lose_weight to gain_muscle increases calorie target."""
        lose_resp = client.get(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        lose_calories = lose_resp["targets"]["calories"]

        client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"goal": "gain_muscle", "weight_kg": 70.0}
        )

        gain_resp = client.get(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        gain_calories = gain_resp["targets"]["calories"]

        assert gain_calories > lose_calories
        print(f"\n  ✓ lose_weight={lose_calories} kcal < gain_muscle={gain_calories} kcal")

        # Restore original goal
        client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"goal": "lose_weight", "weight_kg": 70.0}
        )


    def test_06_update_dietary_restrictions(self, client, shared_state):
        """Can set and retrieve dietary restrictions."""
        resp = client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"dietary_restrictions": ["vegetarian", "gluten-free"]}
        )
        assert resp.status_code == 200

        profile = client.get(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        assert "vegetarian"  in profile["dietary_restrictions"]
        assert "gluten-free" in profile["dietary_restrictions"]

        # Clear restrictions for subsequent tests
        client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"dietary_restrictions": []}
        )


    def test_07_manual_calorie_override(self, client, shared_state):
        """Setting calorie_target directly bypasses Mifflin-St Jeor calculation."""
        resp = client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"calorie_target": 1800.0}
        )
        assert resp.status_code == 200
        assert resp.json()["targets"]["calories"] == 1800.0

        # Restore auto-calculated target
        client.put(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"weight_kg": 70.0, "goal": "lose_weight"}
        )