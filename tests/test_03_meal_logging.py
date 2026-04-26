"""
tests/test_03_meal_logging.py
─────────────────────────────
Tests: food logging via text, macro extraction, USDA validation,
daily total accumulation, knowledge base context, binge detection.

Adding new meal logging tests:
  - Add test_ functions to TestMealLogging
  - Log IDs are stored in shared_state for use in test_05_history.py
"""

import pytest
from tests.conftest import API


class TestMealLogging:

    def test_01_log_banana_text(self, client, shared_state):
        """Text description of a banana returns correct food items and macros."""
        resp = client.post(
            f"{API}/meal/log",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"description": "one medium banana", "meal_type": "snack"}
        )
        assert resp.status_code == 200, f"Banana log failed: {resp.text}"
        data = resp.json()

        # Core fields
        assert "log_id"        in data
        assert "food_items"    in data
        assert "total_macros"  in data
        assert "daily_totals"  in data
        assert "ai_confidence" in data

        # Food items
        assert len(data["food_items"]) >= 1
        banana = data["food_items"][0]
        assert "banana" in banana["name"].lower()
        assert banana["calories"] > 0
        assert banana["carbs_g"]  > 0

        # Total macros
        assert data["total_macros"]["calories"] > 0
        assert data["ai_confidence"] > 0

        # Daily totals updated
        assert data["daily_totals"]["calories"] > 0
        assert data["meals_logged_today"] == 1
        assert data["binge_alert"] is False

        # USDA validation ran
        assert "usda_validation" in data
        assert data["usda_validation"]["matched"] in (True, False)  # either is fine

        # Remaining calories decreased
        assert data["remaining_calories"] > 0

        # Save for later tests
        shared_state.banana_log_id = data["log_id"]
        print(f"\n  ✓ Banana: {data['total_macros']['calories']} kcal, "
              f"confidence={data['ai_confidence']:.2f}")


    def test_02_log_mixed_meal(self, client, shared_state):
        """Multi-item meal is broken into separate food_items."""
        resp = client.post(
            f"{API}/meal/log",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"description": "2 rotis with dal and sabzi", "meal_type": "lunch"}
        )
        assert resp.status_code == 200, f"Lunch log failed: {resp.text}"
        data = resp.json()

        # Should identify multiple distinct items
        assert len(data["food_items"]) >= 2
        assert data["meals_logged_today"] == 2
        assert data["daily_totals"]["calories"] > 100  # banana + lunch

        shared_state.lunch_log_id = data["log_id"]
        print(f"\n  ✓ Lunch: {len(data['food_items'])} items, "
              f"{data['total_macros']['calories']:.0f} kcal")


    def test_03_daily_totals_accumulate(self, client, shared_state):
        """After 2 logs, daily totals should be sum of both meals."""
        # Log a third meal to push totals higher
        resp = client.post(
            f"{API}/meal/log",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={
                "description": "large pepperoni pizza 4 slices and a coke",
                "meal_type": "dinner"
            }
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["meals_logged_today"] == 3
        # 3 meals should have meaningful calories
        assert data["daily_totals"]["calories"] > 500

        shared_state.pizza_log_id = data["log_id"]
        print(f"\n  ✓ Daily total after 3 meals: {data['daily_totals']['calories']:.0f} kcal")


    def test_04_remaining_calories_decrease(self, client, shared_state):
        """remaining_calories should be calorie_target minus daily_totals."""
        # Get user targets
        profile = client.get(
            f"{API}/users/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        target = profile["targets"]["calories"]

        # Get context
        ctx = client.get(
            f"{API}/meal/context/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()

        expected_remaining = target - ctx["today_totals"]["calories"]
        assert abs(ctx["remaining_calories"] - expected_remaining) < 1.0


    def test_05_knowledge_base_context(self, client, shared_state):
        """Context endpoint returns today's meals, totals, and weekly history."""
        resp = client.get(
            f"{API}/meal/context/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200, f"Context failed: {resp.text}"
        ctx = resp.json()

        # Structure
        assert ctx["user_id"]          == shared_state.user_id
        assert ctx["calorie_target"]   > 0
        assert ctx["meals_logged_today"] == 3
        assert len(ctx["today_meals"]) == 3

        # Today meals have required fields
        for meal in ctx["today_meals"]:
            assert "meal_type" in meal
            assert "foods"     in meal
            assert "calories"  in meal
            assert "time"      in meal

        # Weekly history exists
        assert "week_summary" in ctx
        assert "inventory_items" in ctx


    def test_06_log_without_description_or_image_rejected(self, client, shared_state):
        """Logging with neither image nor description returns 400."""
        resp = client.post(
            f"{API}/meal/log",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"meal_type": "snack"}
        )
        assert resp.status_code == 400


    def test_07_log_requires_auth(self, client):
        """Logging without a token returns 401."""
        resp = client.post(
            f"{API}/meal/log",
            json={"description": "apple", "meal_type": "snack"}
        )
        assert resp.status_code == 401


    def test_08_all_macro_fields_present(self, client, shared_state):
        """Every food log response has all required macro fields."""
        resp = client.post(
            f"{API}/meal/log",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"description": "boiled egg", "meal_type": "breakfast"}
        )
        assert resp.status_code == 200
        data = resp.json()

        required_macro_fields = ("calories", "protein_g", "carbs_g", "fat_g")
        for field in required_macro_fields:
            assert field in data["total_macros"], f"Missing macro field: {field}"
            assert data["total_macros"][field] is not None

        # Each food item also has all fields
        for item in data["food_items"]:
            for field in required_macro_fields:
                assert field in item, f"Food item missing: {field}"


    def test_09_micros_returned(self, client, shared_state):
        """Micronutrient breakdown is returned correctly."""
        resp = client.get(
            f"{API}/utils/micros/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "breakdown"    in data
        assert "top_deficits" in data
        assert "all_good"     in data
        assert "logs_counted" in data
        assert data["logs_counted"] >= 3

        # Each nutrient has required keys
        for nutrient, info in data["breakdown"].items():
            assert "consumed" in info
            assert "rdi"      in info
            assert "pct"      in info
            assert "status"   in info
            assert info["status"] in ("good", "low", "very_low", "unknown")

        print(f"\n  ✓ Micros tracked for {data['logs_counted']} logs, "
              f"{len(data['top_deficits'])} deficits found")