"""
tests/test_07_utils.py
──────────────────────
Tests: water logging, water totals, device token registration,
micronutrient breakdown, agent triggers, scheduler status.
"""

import pytest
from tests.conftest import API


class TestUtils:

    # ── Water ──────────────────────────────────────────────────

    def test_01_log_water(self, client, shared_state):
        """POST /utils/water logs ml and returns updated totals."""
        resp = client.post(
            f"{API}/utils/water",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"amount_ml": 500}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["logged_ml"]   == 500.0
        assert data["total_ml"]    >= 500.0
        assert data["target_ml"]   == 2500
        assert data["remaining_ml"] <= 2000.0
        assert 0 <= data["progress_pct"] <= 100
        print(f"\n  ✓ Water: {data['total_ml']}ml logged, {data['progress_pct']}% of target")


    def test_02_water_accumulates(self, client, shared_state):
        """Multiple water logs accumulate correctly."""
        # Log another 250ml
        client.post(
            f"{API}/utils/water",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"amount_ml": 250}
        )

        resp = client.get(
            f"{API}/utils/water/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_ml"] >= 750.0  # at least 500 + 250
        assert data["remaining_ml"] == max(0, 2500 - data["total_ml"])
        assert data["progress_pct"] == min(100, round((data["total_ml"] / 2500) * 100))


    def test_03_water_get_requires_auth(self, client, shared_state):
        """Water GET endpoint requires authentication."""
        resp = client.get(f"{API}/utils/water/{shared_state.user_id}")
        assert resp.status_code == 401


    def test_04_water_other_user_rejected(self, client, shared_state):
        """Cannot view another user's water logs."""
        resp = client.get(
            f"{API}/utils/water/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 403


    # ── Device token ────────────────────────────────────────────

    def test_05_register_device_token(self, client, shared_state):
        """POST /utils/device-token stores APNs token."""
        resp = client.post(
            f"{API}/utils/device-token",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"device_token": "simulated-apns-token-abc123"}
        )
        assert resp.status_code == 200
        assert resp.json()["registered"] is True


    def test_06_update_device_token(self, client, shared_state):
        """Calling device-token again updates the stored token."""
        resp = client.post(
            f"{API}/utils/device-token",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"device_token": "new-token-xyz789"}
        )
        assert resp.status_code == 200
        assert resp.json()["registered"] is True


    # ── Micronutrients ──────────────────────────────────────────

    def test_07_micros_breakdown_structure(self, client, shared_state):
        """GET /utils/micros returns full breakdown with all 11 nutrients."""
        resp = client.get(
            f"{API}/utils/micros/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        expected_nutrients = {
            "iron_mg", "calcium_mg", "vitamin_c_mg", "vitamin_d_iu",
            "vitamin_b12_mcg", "zinc_mg", "magnesium_mg", "potassium_mg",
            "sodium_mg", "omega3_g", "folate_mcg"
        }
        assert expected_nutrients.issubset(set(data["breakdown"].keys()))

        # Each nutrient has required sub-fields
        for name, info in data["breakdown"].items():
            assert "consumed" in info, f"{name} missing 'consumed'"
            assert "rdi"      in info, f"{name} missing 'rdi'"
            assert "pct"      in info, f"{name} missing 'pct'"
            assert "status"   in info, f"{name} missing 'status'"
            assert info["status"] in ("good", "low", "very_low", "unknown")
            assert 0 <= info["pct"] <= 100

        assert "top_deficits" in data
        assert len(data["top_deficits"]) <= 4   # max 4 deficits shown
        assert "all_good"     in data
        assert "logs_counted" in data


    def test_08_micros_other_user_rejected(self, client, shared_state):
        """Cannot view another user's micronutrients."""
        resp = client.get(
            f"{API}/utils/micros/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 403


class TestCoach:

    def test_01_today_coach_card(self, client, shared_state):
        """GET /coach/today returns a home-screen coach card."""
        resp = client.get(
            f"{API}/coach/today",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200, f"Coach card failed: {resp.text}"
        data = resp.json()

        assert "card" in data
        assert "progress" in data
        assert "signals" in data
        assert "title" in data["card"]
        assert "message" in data["card"]
        assert "action" in data["card"]
        assert "remaining_calories" in data["progress"]


    def test_02_today_coach_card_requires_auth(self, client):
        """Coach card endpoint requires authentication."""
        resp = client.get(f"{API}/coach/today")
        assert resp.status_code == 401


class TestAgents:

    def test_01_scheduler_status(self, client, shared_state):
        """GET /agents/scheduler-status shows running scheduler with 2 jobs."""
        resp = client.get(
            f"{API}/agents/scheduler-status",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["scheduler_running"] is True
        assert data["total_jobs"] >= 2

        job_ids = [j["id"] for j in data["jobs"]]
        assert "coach_morning_run"       in job_ids
        assert "inventory_expiry_refresh" in job_ids

        for job in data["jobs"]:
            assert "name"          in job
            assert "next_run_time" in job
            assert "trigger"       in job

        print(f"\n  ✓ Scheduler running with {data['total_jobs']} jobs")


    def test_02_trigger_coach_agent(self, client, shared_state):
        """POST /agents/trigger-coach runs coach agent and returns outcome."""
        resp = client.post(
            f"{API}/agents/trigger-coach",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "triggered_for" in data
        assert "outcome"       in data
        assert data["triggered_for"] == shared_state.user_id

        outcome = data["outcome"]
        assert "action" in outcome
        assert outcome["action"] in ("plan_generated", "skipped", "failed")

        if outcome["action"] == "plan_generated":
            assert "plan_id" in outcome
            assert "trigger" in outcome
            assert outcome["trigger"] in (
                "daily_routine", "binge_recovery", "inventory_expiry"
            )

        print(f"\n  ✓ Coach agent: action={outcome['action']}")


    def test_03_agents_require_auth(self, client):
        """Agent endpoints reject unauthenticated requests."""
        resp = client.post(f"{API}/agents/trigger-coach")
        assert resp.status_code == 401

        resp = client.get(f"{API}/agents/scheduler-status")
        assert resp.status_code == 401


    def test_04_trigger_coach_all_requires_admin(self, client, shared_state):
        """POST /agents/trigger-coach-all is admin-only."""
        resp = client.post(
            f"{API}/agents/trigger-coach-all",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 403


    def test_05_rate_limit_fires_on_meal_log(self, client, shared_state):
        """After 20 rapid /meal/log requests, 21st should return 429."""
        status_codes = []
        for _ in range(21):
            r = client.post(
                f"{API}/meal/log",
                headers={"Authorization": f"Bearer {shared_state.access_token}"},
                json={"description": "apple", "meal_type": "snack"}
            )
            status_codes.append(r.status_code)

        successes = status_codes.count(200)
        rate_limited = status_codes.count(429)

        assert rate_limited >= 1, (
            f"Rate limit never fired — all {len(status_codes)} returned 200"
        )
        print(f"\n  ✓ Rate limit: {successes} OK, {rate_limited} rate-limited")
