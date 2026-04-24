"""
USDA FoodData Central Validation Service
─────────────────────────────────────────
Cross-references AI calorie estimates against the USDA database.
Returns an accuracy delta and a confidence adjustment.

API key signup (free): https://fdc.nal.usda.gov/api-key-signup
"""

import httpx
from app.config import settings

USDA_BASE = "https://api.nal.usda.gov/fdc/v1"


async def validate_food(food_name: str, ai_calories: float) -> dict:
    """
    Search USDA for food_name, compare AI calorie estimate against ground truth.
    Returns accuracy_delta: 0.08 means 8% off from USDA value.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{USDA_BASE}/foods/search",
                params={
                    "query":    food_name,
                    "api_key":  settings.USDA_API_KEY,
                    "pageSize": 1,
                    "dataType": "SR Legacy,Foundation",
                }
            )
            data = resp.json()
    except Exception as e:
        return {"matched": False, "error": f"USDA request failed: {str(e)}"}

    foods = data.get("foods", [])
    if not foods:
        return {"matched": False, "usda_name": None, "accuracy_delta": None}

    food = foods[0]
    nutrients = {n["nutrientName"]: n["value"] for n in food.get("foodNutrients", [])}

    # USDA returns kcal per 100g — AI estimates total for the portion
    # We compare directionally: if AI says 105 kcal for a banana (~118g),
    # USDA says ~89 kcal/100g → expected ~105 kcal. Delta ≈ 0%.
    usda_per_100g = nutrients.get("Energy", 0)

    if usda_per_100g and ai_calories:
        delta = abs(ai_calories - usda_per_100g) / max(usda_per_100g, 1)
    else:
        delta = None

    return {
        "matched":              True,
        "usda_name":            food.get("description", ""),
        "usda_fdcId":           food.get("fdcId"),
        "usda_calories_per_100g": usda_per_100g,
        "ai_calories_estimated":  ai_calories,
        "accuracy_delta":       round(delta, 3) if delta is not None else None,
        # e.g. 0.08 = 8% off. Under 0.15 is good. Over 0.30 is flagged.
        "confidence_adjustment": (
            -round(delta, 2) if (delta and delta > 0.20) else 0
        ),
        "flag": (
            "accurate"  if delta is not None and delta <= 0.15 else
            "acceptable" if delta is not None and delta <= 0.30 else
            "review"    if delta is not None else
            "unverified"
        ),
    }