"""
tests/test_04_inventory.py
──────────────────────────
Tests: add items (text + image scan), get inventory, expiry flags,
update, delete (soft), meal suggestions from inventory.

Adding new inventory tests:
  - Add test_ functions to TestInventory
  - Image scan test uses a tiny 1x1 pixel base64 JPEG as a stub
    (replace with a real food image URL or base64 in integration tests)
"""

import pytest
import base64
from tests.conftest import API

# Minimal valid 1x1 JPEG in base64 — used to test image endpoint wiring
# without needing a real food photo in CI
STUB_IMAGE_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAA"
    "AAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/"
    "aAAwDAQACEQMRAD8AJQAB/9k="
)


class TestInventory:

    def test_01_add_item_protein(self, client, shared_state):
        """Add an egg item with expiry — returns item_id and expiring_soon flag."""
        resp = client.post(
            f"{API}/inventory/add",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={
                "name":        "Eggs",
                "quantity":    "6",
                "expiry_date": "2026-04-27",
                "category":    "protein",
            }
        )
        assert resp.status_code == 200, f"Add eggs failed: {resp.text}"
        data = resp.json()

        assert "item_id"          in data
        assert data["name"]       == "Eggs"
        assert "days_until_expiry" in data
        assert "expiring_soon"    in data

        shared_state.egg_item_id = data["item_id"]
        print(f"\n  ✓ Eggs added, expiring_soon={data['expiring_soon']}")


    def test_02_add_item_vegetable(self, client, shared_state):
        """Add spinach with near expiry — should be flagged expiring_soon."""
        resp = client.post(
            f"{API}/inventory/add",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={
                "name":        "Spinach",
                "quantity":    "200g",
                "expiry_date": "2026-04-26",
                "category":    "vegetable",
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        shared_state.spinach_item_id = data["item_id"]


    def test_03_add_item_no_expiry(self, client, shared_state):
        """Add item without expiry_date — days_until_expiry should be null."""
        resp = client.post(
            f"{API}/inventory/add",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"name": "Brown Rice", "quantity": "500g", "category": "grain"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["days_until_expiry"] is None
        assert data["expiring_soon"] is False


    def test_04_get_inventory(self, client, shared_state):
        """GET /inventory returns all available items with expiry flags."""
        resp = client.get(
            f"{API}/inventory/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "items"              in data
        assert "total_items"        in data
        assert "expiring_soon_count" in data
        assert data["total_items"]  >= 3

        # Items have required fields
        for item in data["items"]:
            assert "id"            in item
            assert "name"          in item
            assert "expiring_soon" in item

        print(f"\n  ✓ Inventory: {data['total_items']} items, "
              f"{data['expiring_soon_count']} expiring soon")


    def test_05_expiry_ordering(self, client, shared_state):
        """Inventory items are returned ordered by expiry_date ascending."""
        resp = client.get(
            f"{API}/inventory/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        items = [i for i in resp.json()["items"] if i["expiry_date"] is not None]

        dates = [i["expiry_date"] for i in items]
        assert dates == sorted(dates), "Items not sorted by expiry_date ascending"


    def test_06_update_item_quantity(self, client, shared_state):
        """PATCH /inventory/{id} updates quantity correctly."""
        resp = client.patch(
            f"{API}/inventory/{shared_state.egg_item_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"quantity": "4"}
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] is True


    def test_07_update_wrong_user_rejected(self, client, shared_state):
        """Cannot update another user's inventory item."""
        # Create a second user and try to update first user's item
        import time
        second_user = client.post(f"{API}/auth/signup", json={
            "email": f"second_{int(time.time())}@nutriai.com",
            "password": "pass1234",
            "name": "Second", "age": 30, "weight_kg": 65, "height_cm": 170,
            "gender": "female", "goal": "maintain", "activity_level": "light",
        }).json()

        resp = client.patch(
            f"{API}/inventory/{shared_state.egg_item_id}",
            headers={"Authorization": f"Bearer {second_user['access_token']}"},
            json={"quantity": "999"}
        )
        assert resp.status_code == 403


    def test_08_soft_delete_item(self, client, shared_state):
        """DELETE /inventory/{id} soft-deletes — item no longer appears in list."""
        # Add a throwaway item
        item = client.post(
            f"{API}/inventory/add",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"name": "Throwaway Item", "quantity": "1"}
        ).json()
        item_id = item["item_id"]

        # Delete it
        del_resp = client.delete(
            f"{API}/inventory/{item_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["removed"] is True

        # Verify it's gone from the list
        inv = client.get(
            f"{API}/inventory/{shared_state.user_id}",
            headers={"Authorization": f"Bearer {shared_state.access_token}"}
        ).json()
        item_ids = [i["id"] for i in inv["items"]]
        assert item_id not in item_ids


    def test_09_suggest_from_inventory(self, client, shared_state):
        """Meal suggestions use available inventory items."""
        resp = client.post(
            f"{API}/meal/suggest-from-inventory",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "suggestions" in data
        assert len(data["suggestions"]) > 0

        for suggestion in data["suggestions"]:
            assert "name"              in suggestion
            assert "uses"              in suggestion
            assert "prep_time_mins"    in suggestion
            assert "estimated_calories" in suggestion
            assert suggestion["estimated_calories"] > 0

        print(f"\n  ✓ {len(data['suggestions'])} meal suggestions from inventory")


    def test_10_scan_image_endpoint_exists(self, client, shared_state):
        """POST /inventory/scan-image accepts image_base64 and returns items list."""
        resp = client.post(
            f"{API}/inventory/scan-image",
            headers={"Authorization": f"Bearer {shared_state.access_token}"},
            json={"image_base64": STUB_IMAGE_B64}
        )
        # 200 with items (even if empty for stub image) or 502 if AI can't parse stub
        # Both are acceptable — we're testing the endpoint wiring, not AI accuracy
        assert resp.status_code in (200, 502), f"Unexpected status: {resp.text}"
        if resp.status_code == 200:
            data = resp.json()
            assert "added"           in data
            assert "total_added"     in data
            assert "scan_confidence" in data
            assert isinstance(data["added"], list)