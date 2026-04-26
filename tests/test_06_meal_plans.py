"""
tests/test_06_meal_plans.py
───────────────────────────
Tests: plan generation, plan acceptance, active plan retrieval,
binge recovery mode detection, weekly revision.
"""

import pytest
from tests.conftest import API


class TestMealPlans:

    def test_01_generate_plan(self, client, shared_state):
        """POST /plan/generate returns a valid meal plan structure."""
        resp = client.post(
            f"{API}/plan/generate",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"trigger": "user_request", "save": True}
        )
        assert resp.status_code == 200, f"Plan generate failed: {resp.text}"
        data = resp.json()

        assert "plan_summary"      in data
        assert "meals"             in data
        assert "total_plan_macros" in data
        assert "trigger"           in data
        assert "plan_id"           in data

        assert len(data["meals"]) > 0
        assert data["trigger"] == "user_request"

        # Each meal has required fields
        for meal in data["meals"]:
            assert "meal_type"         in meal
            assert "name"              in meal
            assert "ingredients"       in meal
            assert "estimated_macros"  in meal
            assert "recipe_steps"      in meal
            assert "prep_time_mins"    in meal
            assert len(meal["recipe_steps"]) > 0
            assert meal["estimated_macros"]["calories"] > 0

        shared_state.plan_id = data["plan_id"]
        print(f"\n  ✓ Plan generated: {len(data['meals'])} meals, "
              f"summary='{data['plan_summary'][:50]}...'")


    def test_02_generate_plan_without_save(self, client, shared_state):
        """save=False returns a plan but does not persist it (no plan_id)."""
        resp = client.post(
            f"{API}/plan/generate",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"trigger": "user_request", "save": False}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_id"] is None
        assert len(data["meals"]) > 0


    def test_03_accept_plan(self, client, shared_state):
        """POST /plan/accept/{id} marks plan as active."""
        resp = client.post(
            f"{API}/plan/accept/{shared_state.plan_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["accepted"] is True
        assert resp.json()["plan_id"] == shared_state.plan_id


    def test_04_get_active_plan(self, client, shared_state):
        """GET /plan/active/{id} returns the accepted plan."""
        resp = client.get(
            f"{API}/plan/active/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["active_plan"] is not None
        assert data["active_plan"]["plan_id"] == shared_state.plan_id
        assert "meals"        in data["active_plan"]
        assert "plan_summary" in data["active_plan"]
        assert "plan_date"    in data["active_plan"]


    def test_05_accept_nonexistent_plan(self, client, shared_state):
        """Accepting a non-existent plan returns 404."""
        resp = client.post(
            f"{API}/plan/accept/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 404


    def test_06_plan_macros_within_remaining(self, client, shared_state):
        """Plan total macros should be close to remaining daily calories."""
        ctx = client.get(
            f"{API}/meal/context/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        remaining = ctx["remaining_calories"]

        plan = client.get(
            f"{API}/plan/active/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()["active_plan"]

        plan_calories = plan["total_plan_macros"].get("calories", 0)

        # Plan should not wildly exceed remaining (allow 20% buffer)
        if remaining > 200:
            assert plan_calories <= remaining * 1.20, (
                f"Plan ({plan_calories} kcal) far exceeds remaining ({remaining} kcal)"
            )
        print(f"\n  ✓ Remaining: {remaining:.0f} kcal, Plan: {plan_calories:.0f} kcal")


    def test_07_week_revision_returns_valid_structure(self, client, shared_state):
        """POST /plan/revise-week returns a structured revision response."""
        resp = client.post(
            f"{API}/plan/revise-week",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        # Must have these keys regardless of whether revision was needed
        assert "message"      in data
        assert "plans"        in data
        assert isinstance(data["plans"], list)

        # If plans were generated, they have the right shape
        for plan in data["plans"]:
            assert "date"             in plan
            assert "adjusted_target"  in plan
            assert "plan"             in plan

        print(f"\n  ✓ Week revision: {len(data['plans'])} days revised")


    def test_08_plan_requires_auth(self, client):
        """Plan endpoints reject unauthenticated requests."""
        resp = client.post(
            f"{API}/plan/generate",
            json={"trigger": "user_request", "save": False}
        )
        assert resp.status_code == 401