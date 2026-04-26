"""
tests/test_05_history.py
────────────────────────
Tests: daily history chart, per-date log list, edit log, delete log,
daily summary correction after edits, streak tracking.
"""

import pytest
from datetime import date
from tests.conftest import API


class TestHistory:

    def test_01_daily_history_7_days(self, client, shared_state):
        """GET /history/{id}/daily returns 7 entries with today populated."""
        resp = client.get(
            f"{API}/history/{shared_state.user_id}/daily?days=7",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "days"   in data
        assert "streak" in data
        assert "period" in data
        assert len(data["days"]) == 7

        # Today's entry should have meals logged (from test_03)
        today_entry = data["days"][-1]  # last entry is today
        assert today_entry["date"]         == str(date.today())
        assert today_entry["calories"]     > 0
        assert today_entry["meals_logged"] >= 3
        assert today_entry["target_calories"] > 0

        # Streak should be at least 1 (today)
        assert data["streak"] >= 1

        # Past days should be zeros
        for day in data["days"][:-1]:
            assert day["meals_logged"] == 0

        print(f"\n  ✓ 7-day history: today={today_entry['calories']:.0f} kcal, "
              f"streak={data['streak']}")


    def test_02_daily_history_custom_range(self, client, shared_state):
        """days param controls number of entries returned."""
        for days in [1, 14, 30]:
            resp = client.get(
                f"{API}/history/{shared_state.user_id}/daily?days={days}",
                headers={"Authorization": f"Bearer {shared_state.access_token}"}
            )
            assert resp.status_code == 200
            assert len(resp.json()["days"]) == days


    def test_03_get_logs_today(self, client, shared_state):
        """GET /history/{id}/logs returns today's meals with full detail."""
        today = str(date.today())
        resp = client.get(
            f"{API}/history/{shared_state.user_id}/logs?date={today}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["date"]       == today
        assert "logs"             in data
        assert data["total_logs"] >= 3

        # Each log has required fields
        for log in data["logs"]:
            assert "log_id"       in log
            assert "meal_type"    in log
            assert "logged_at"    in log
            assert "food_items"   in log
            assert "macros"       in log
            assert "ai_confidence" in log
            for field in ("calories", "protein_g", "carbs_g", "fat_g"):
                assert field in log["macros"]


    def test_04_get_logs_empty_date(self, client, shared_state):
        """Requesting logs for a past date with no data returns empty list."""
        resp = client.get(
            f"{API}/history/{shared_state.user_id}/logs?date=2020-01-01",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["total_logs"] == 0
        assert resp.json()["logs"] == []


    def test_05_edit_log_calories(self, client, shared_state):
        """PATCH /history/log/{id} updates calories and corrects daily summary."""
        # Get current daily total
        ctx_before = client.get(
            f"{API}/meal/context/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        calories_before = ctx_before["today_totals"]["calories"]

        # Edit banana log — add 50 kcal
        resp = client.patch(
            f"{API}/history/log/{shared_state.banana_log_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"calories": 155.0}  # was ~105
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] is True
        assert resp.json()["macros"]["calories"] == 155.0

        # Daily total should have increased by ~50
        ctx_after = client.get(
            f"{API}/meal/context/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        calories_after = ctx_after["today_totals"]["calories"]
        assert abs((calories_after - calories_before) - 50.0) < 2.0

        print(f"\n  ✓ Edit: daily calories {calories_before:.0f} → {calories_after:.0f}")


    def test_06_edit_log_wrong_user_rejected(self, client, shared_state):
        """Cannot edit another user's food log."""
        import time
        other = client.post(f"{API}/auth/signup", json={
            "email": f"other_{int(time.time())}@nutriai.com",
            "password": "pass1234", "name": "Other",
            "age": 28, "weight_kg": 68, "height_cm": 172,
            "gender": "male", "goal": "maintain", "activity_level": "light",
        }).json()

        resp = client.patch(
            f"{API}/history/log/{shared_state.banana_log_id}",
            headers={"Authorization": f"Bearer {other['access_token']}"},
            json={"calories": 999}
        )
        assert resp.status_code == 403


    def test_07_delete_log_reverts_summary(self, client, shared_state):
        """DELETE /history/log/{id} removes the entry and reverts daily totals."""
        ctx_before = client.get(
            f"{API}/meal/context/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        meals_before   = ctx_before["meals_logged_today"]
        calories_before = ctx_before["today_totals"]["calories"]

        # Delete banana log
        resp = client.delete(
            f"{API}/history/log/{shared_state.banana_log_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Context should reflect deletion
        ctx_after = client.get(
            f"{API}/meal/context/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        assert ctx_after["meals_logged_today"] == meals_before - 1
        assert ctx_after["today_totals"]["calories"] < calories_before

        print(f"\n  ✓ Delete: meals {meals_before}→{ctx_after['meals_logged_today']}, "
              f"calories {calories_before:.0f}→{ctx_after['today_totals']['calories']:.0f}")


    def test_08_delete_nonexistent_log(self, client, shared_state):
        """Deleting a non-existent log returns 404."""
        resp = client.delete(
            f"{API}/history/log/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 404


    def test_09_history_requires_auth(self, client, shared_state):
        """History endpoints reject unauthenticated requests."""
        resp = client.get(f"{API}/history/{shared_state.user_id}/daily")
        assert resp.status_code == 401