"""
AI Service — Groq Integration
──────────────────────────────
All prompts are context-aware: they receive the user's knowledge base
context dict before generating any response, making every call
"remember" the user's history, targets, and inventory.

Models used:
  - Food image analysis : meta-llama/llama-4-scout-17b-16e-instruct  (vision)
  - Meal plan / text    : llama-3.3-70b-versatile                    (text, faster + cheaper)

NOTE: analyze_food_agentic lives in agents/analyser_agent.py
      It is NOT imported here to avoid circular imports.
      meal.py imports it directly from agents.analyser_agent.
"""

import json
from groq import Groq
from app.config import settings

client = Groq(api_key=settings.GROQ_API_KEY)

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
TEXT_MODEL   = "llama-3.3-70b-versatile"


# ─────────────────────────────────────────────
# Helper: robustly parse JSON from model output
# ─────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    """
    Robustly extract JSON from model response.
    Handles: raw JSON, ```json fences, ``` fences, leading prose before {
    """
    raw = raw.strip()

    # Strip markdown fences
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # If model added prose before the JSON, find the first { or [
    if not raw.startswith(("{", "[")):
        brace   = raw.find("{")
        bracket = raw.find("[")
        if brace == -1 and bracket == -1:
            raise ValueError(f"No JSON object found in response: {raw[:200]}")
        start = min(x for x in [brace, bracket] if x != -1)
        raw = raw[start:]

    # Try parsing as-is first
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        # Model appended prose after the JSON — strip it
        last_brace   = raw.rfind("}")
        last_bracket = raw.rfind("]")
        end = max(last_brace, last_bracket)
        if end != -1:
            return json.loads(raw[:end + 1])
        raise


# ─────────────────────────────────────────────
# Helper: guarantee food response shape
# ─────────────────────────────────────────────

def _normalise_food_response(result: dict) -> dict:
    """
    Ensures the food analysis response always has every expected field,
    regardless of how the model structured its output.
    Called immediately after _parse_json in analyze_food().
    Prevents all KeyError / TypeError crashes downstream.
    """
    # ── food_items ──────────────────────────────
    if "food_items" not in result or not isinstance(result["food_items"], list):
        result["food_items"] = []

    for item in result["food_items"]:
        for field in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g"):
            if field not in item or item[field] is None:
                item[field] = 0.0
            else:
                item[field] = float(item[field])
        item.setdefault("name",     "Unknown food")
        item.setdefault("quantity", "1 serving")

    # ── total ────────────────────────────────────
    if "total" not in result or not isinstance(result.get("total"), dict):
        # Compute from food_items if model forgot to include it
        result["total"] = {
            "calories":  sum(i["calories"]  for i in result["food_items"]),
            "protein_g": sum(i["protein_g"] for i in result["food_items"]),
            "carbs_g":   sum(i["carbs_g"]   for i in result["food_items"]),
            "fat_g":     sum(i["fat_g"]     for i in result["food_items"]),
            "fiber_g":   sum(i["fiber_g"]   for i in result["food_items"]),
        }
    else:
        for field in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g"):
            result["total"].setdefault(field, 0.0)

    # ── micros ───────────────────────────────────
    default_micros = {
        "iron_mg": 0, "calcium_mg": 0, "vitamin_c_mg": 0,
        "vitamin_d_iu": 0, "vitamin_b12_mcg": 0, "zinc_mg": 0,
        "magnesium_mg": 0, "potassium_mg": 0, "sodium_mg": 0,
        "omega3_g": 0, "folate_mcg": 0,
    }
    if "micros" not in result or not isinstance(result.get("micros"), dict):
        result["micros"] = default_micros
    else:
        for k, v in default_micros.items():
            result["micros"].setdefault(k, v)

    # ── confidence ───────────────────────────────
    raw_conf = result.get("confidence")
    if raw_conf is None or not isinstance(raw_conf, (int, float)):
        result["confidence"] = 0.7   # safe default
    else:
        result["confidence"] = max(0.0, min(1.0, float(raw_conf)))

    # ── notes ────────────────────────────────────
    result.setdefault("notes", "")

    return result


# ─────────────────────────────────────────────
# 1. Food analysis — image and/or text
# ─────────────────────────────────────────────

async def analyze_food(
    image_base64: str | None,
    description: str,
    context: dict,
) -> dict:
    """
    Analyse a meal from image and/or text description.
    Returns a normalised dict — all fields guaranteed to exist.
    Called by analyser_agent.analyze_food_agentic() which wraps this
    with a confidence-check loop before returning to meal.py.
    """
    restrictions = context.get("dietary_restrictions") or []
    restriction_note = (
        f"Note: user is {', '.join(restrictions)}." if restrictions else ""
    )
    remaining = context.get("remaining_calories", 2000)

    system_prompt = f"""You are a precise nutrition analysis AI.
{restriction_note}
The user has {remaining:.0f} kcal remaining today — use this only as context, not to alter your estimates.
Always estimate based on what you actually see/read. Be accurate, not aspirational.

Return ONLY valid JSON. No explanation, no markdown, no preamble.
"""

    user_content = []

    if image_base64:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
        })

    text_input = description if description else "Analyze the food in this image."
    user_content.append({
        "type": "text",
        "text": f"""{text_input}

Return this exact JSON structure:
{{
  "food_items": [
    {{
      "name": "Grilled chicken breast",
      "quantity": "150g",
      "calories": 248,
      "protein_g": 46.5,
      "carbs_g": 0.0,
      "fat_g": 5.4,
      "fiber_g": 0.0
    }}
  ],
  "total": {{
    "calories": 248,
    "protein_g": 46.5,
    "carbs_g": 0.0,
    "fat_g": 5.4,
    "fiber_g": 0.0
  }},
  "micros": {{
    "iron_mg": 1.2,
    "calcium_mg": 15,
    "vitamin_c_mg": 0,
    "vitamin_d_iu": 0,
    "vitamin_b12_mcg": 0.8,
    "zinc_mg": 2.4,
    "magnesium_mg": 32,
    "potassium_mg": 430,
    "sodium_mg": 75,
    "omega3_g": 0.1,
    "folate_mcg": 8
  }},
  "confidence": 0.85,
  "notes": "Portion estimated from plate reference"
}}

Rules:
- List every distinct food item separately
- confidence: 0.0-1.0 (how clearly visible/described the food is)
- If you cannot identify something, still estimate with low confidence
- Quantities in grams or common measures (1 cup, 2 tbsp)
- Always include micros block even if values are 0
"""
    })

    model = VISION_MODEL if image_base64 else TEXT_MODEL

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            # Always pass user_content (the list) — never the plain string.
            # user_content contains the full JSON schema instructions.
            # Passing text_input instead would strip the format prompt
            # and cause the model to return unstructured output.
            {"role": "user", "content": user_content},
        ],
        max_tokens=1000,
        temperature=0.1,
    )

    raw = response.choices[0].message.content
    result = _parse_json(raw)
    return _normalise_food_response(result)   # ← normalise called here


# ─────────────────────────────────────────────
# 2. Meal plan generator
# ─────────────────────────────────────────────

async def generate_meal_plan(context: dict, trigger: str = "daily_routine") -> dict:
    """
    Generate a meal plan for the remaining meals today.
    Trigger: daily_routine | binge_recovery | inventory_expiry | user_request
    """
    binge_mode    = context.get("binge_recovery_mode", False)
    binge_days    = context.get("binge_days_count", 0)
    inventory     = context.get("inventory_detail", [])
    expiring_soon = context.get("expiring_soon", [])
    restrictions  = context.get("dietary_restrictions", [])
    remaining_cal = context.get("remaining_calories", 2000)
    remaining_pro = context.get("remaining_protein_g", 150)
    week_summary  = context.get("week_summary", [])
    today_meals   = context.get("today_meals", [])

    inventory_str = (
        "\n".join(f"- {i['name']} ({i.get('quantity','?')})" for i in inventory)
        if inventory else "No inventory tracked yet"
    )
    expiring_str = ", ".join(expiring_soon) if expiring_soon else "none"

    week_str = (
        "\n".join(
            f"- {d['date']}: {d['calories']} kcal "
            f"({'OVER' if d['vs_target'] > 0 else 'under'} by {abs(d['vs_target'])} kcal)"
            f"{' [BINGE]' if d['is_binge_day'] else ''}"
            for d in week_summary
        ) if week_summary else "No history yet"
    )

    binge_instruction = ""
    if binge_mode:
        binge_instruction = f"""
IMPORTANT — BINGE RECOVERY MODE:
The user has had {binge_days} high-calorie day(s) this week (see weekly history).
Adjust the plan to be ~{min(300, binge_days * 150)} kcal below their normal target today.
Focus on high-protein, high-fiber, lower-carb meals to rebalance.
Do NOT make it feel punishing — keep meals satisfying and enjoyable.
"""

    prompt = f"""You are a compassionate, expert nutritionist AI.

USER TARGETS:
- Daily calories: {context['calorie_target']} kcal
- Protein: {context['protein_target_g']}g | Carbs: {context['carbs_target_g']}g | Fat: {context['fat_target_g']}g
- Dietary restrictions: {', '.join(restrictions) if restrictions else 'none'}

TODAY SO FAR:
{json.dumps(today_meals, indent=2) if today_meals else 'Nothing logged yet'}

REMAINING TODAY:
- Calories: {remaining_cal:.0f} kcal
- Protein: {remaining_pro:.0f}g

WEEKLY HISTORY:
{week_str}
{binge_instruction}

AVAILABLE INVENTORY:
{inventory_str}

EXPIRING SOON (prioritise these): {expiring_str}

TASK: Generate a meal plan for the remaining meals today.
- Prefer using inventory items, especially expiring ones
- Each meal must have a simple recipe (steps a home cook can follow)
- Keep total macros close to the REMAINING targets above

Return ONLY this JSON structure:
{{
  "plan_summary": "Brief 1-line explanation of why this plan was chosen",
  "meals": [
    {{
      "meal_type": "lunch",
      "name": "Paneer Tikka with Brown Rice",
      "ingredients": ["200g paneer", "100g brown rice", "1 bell pepper"],
      "estimated_macros": {{
        "calories": 520,
        "protein_g": 28,
        "carbs_g": 55,
        "fat_g": 18,
        "fiber_g": 4
      }},
      "prep_time_mins": 20,
      "recipe_steps": [
        "Cube paneer and marinate in yogurt + spices for 10 mins",
        "Grill on medium heat for 8 mins, turning once",
        "Cook rice in 2x water for 18 mins"
      ],
      "uses_expiring_items": false
    }}
  ],
  "total_plan_macros": {{
    "calories": 520,
    "protein_g": 28,
    "carbs_g": 55,
    "fat_g": 18
  }}
}}
"""

    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0.4,
    )

    result = _parse_json(response.choices[0].message.content)
    result.setdefault("plan_summary", "Meal plan generated based on your targets.")
    result.setdefault("meals", [])
    result.setdefault("total_plan_macros", {})
    result["trigger"]       = trigger
    result["binge_recovery"] = binge_mode
    return result


# ─────────────────────────────────────────────
# 3. Inventory-aware meal suggestions
# ─────────────────────────────────────────────

async def suggest_from_inventory(context: dict) -> dict:
    inventory     = context.get("inventory_detail", [])
    expiring_soon = context.get("expiring_soon", [])
    restrictions  = context.get("dietary_restrictions", [])

    if not inventory:
        return {"suggestions": [], "message": "Add items to your inventory first."}

    inventory_str = "\n".join(
        f"- {i['name']} ({i.get('quantity','?')})" for i in inventory
    )

    prompt = f"""Given these available ingredients, suggest 3 quick meals.
Dietary restrictions: {', '.join(restrictions) if restrictions else 'none'}
Must use expiring items if possible: {', '.join(expiring_soon) if expiring_soon else 'none'}

Available:
{inventory_str}

Return ONLY JSON:
{{
  "suggestions": [
    {{
      "name": "Egg Fried Rice",
      "uses": ["eggs", "rice", "spring onions"],
      "prep_time_mins": 15,
      "estimated_calories": 450
    }}
  ]
}}"""

    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
        temperature=0.5,
    )

    result = _parse_json(response.choices[0].message.content)
    result.setdefault("suggestions", [])
    return result


async def suggest_what_to_eat_now(
    context: dict,
    meal_type: str | None = None,
    max_options: int = 3,
) -> dict:
    """
    Suggest immediate meal/snack options based on today's remaining budget,
    inventory, expiring items, dietary restrictions, and recent meals.
    """
    inventory = context.get("inventory_detail", [])
    expiring_soon = context.get("expiring_soon", [])
    restrictions = context.get("dietary_restrictions", [])
    today_meals = context.get("today_meals", [])
    remaining_cal = context.get("remaining_calories", 2000)
    remaining_pro = context.get("remaining_protein_g", 150)

    inventory_str = (
        "\n".join(
            f"- {i['name']} ({i.get('quantity') or '?'}, expires {i.get('expiry_date') or 'unknown'})"
            for i in inventory
        )
        if inventory else "No inventory tracked yet"
    )

    prompt = f"""You are a practical nutrition coach.

The user wants to know what they can eat right now.

USER CONTEXT:
- Meal type requested: {meal_type or 'best fit'}
- Calories remaining today: {remaining_cal:.0f}
- Protein remaining today: {remaining_pro:.0f}g
- Dietary restrictions: {', '.join(restrictions) if restrictions else 'none'}
- Expiring soon: {', '.join(expiring_soon) if expiring_soon else 'none'}
- Meals already eaten: {json.dumps(today_meals, indent=2) if today_meals else 'none logged'}

AVAILABLE INVENTORY:
{inventory_str}

TASK:
Suggest up to {max(1, min(max_options, 5))} realistic options the user can eat now.
Prefer inventory items, especially expiring ones. If inventory is empty, suggest simple common options.
Keep options close to the remaining calorie and protein budget.

Return ONLY JSON:
{{
  "summary": "Short reason these options fit right now",
  "options": [
    {{
      "name": "Paneer spinach bowl",
      "meal_type": "dinner",
      "why_this_fits": "Uses spinach before expiry and closes the protein gap",
      "uses_inventory": ["paneer", "spinach"],
      "missing_items": ["lemon"],
      "estimated_macros": {{
        "calories": 480,
        "protein_g": 32,
        "carbs_g": 38,
        "fat_g": 18,
        "fiber_g": 7
      }},
      "prep_time_mins": 15,
      "log_hint": "Paneer spinach bowl, 1 serving"
    }}
  ],
  "nudge": "One sentence coaching nudge"
}}"""

    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0.35,
    )

    result = _parse_json(response.choices[0].message.content)
    result.setdefault("summary", "Options generated from your current context.")
    result.setdefault("options", [])
    result.setdefault("nudge", "")
    return result

async def scan_inventory_image(image_base64: str) -> dict:
    """
    Identify grocery/fridge items from a photo.
    Returns a list of items ready to be bulk-added to inventory.
    Called by POST /inventory/scan-image
    """
    system_prompt = """You are a grocery and pantry inventory AI.
Analyse the image and identify every distinct food item you can see.
For each item estimate: quantity visible, likely category, and approximate shelf life.

Return ONLY valid JSON. No explanation, no markdown, no preamble."""

    prompt = """Identify all food/grocery items in this image.

Return this exact JSON:
{
  "items": [
    {
      "name": "Eggs",
      "quantity": "6",
      "category": "protein",
      "estimated_shelf_days": 21,
      "confidence": 0.95
    },
    {
      "name": "Spinach",
      "quantity": "200g",
      "category": "vegetable",
      "estimated_shelf_days": 4,
      "confidence": 0.88
    }
  ],
  "scan_confidence": 0.9,
  "notes": "Clear lighting, items easily identifiable"
}

Categories: protein | vegetable | dairy | grain | fruit | spice | beverage | other
estimated_shelf_days: realistic fridge/pantry life from today
confidence per item: 0.0-1.0
scan_confidence: overall image quality score"""

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    },
                    {"type": "text", "text": prompt}
                ]
            }
        ],
        max_tokens=1000,
        temperature=0.1,
    )

    result = _parse_json(response.choices[0].message.content)

    # Normalise response
    result.setdefault("items", [])
    result.setdefault("scan_confidence", 0.7)
    result.setdefault("notes", "")

    for item in result["items"]:
        item.setdefault("name", "Unknown item")
        item.setdefault("quantity", None)
        item.setdefault("category", "other")
        item.setdefault("estimated_shelf_days", 7)
        item.setdefault("confidence", 0.7)

    return result
