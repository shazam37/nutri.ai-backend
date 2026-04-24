"""
AI Service — Groq Integration
──────────────────────────────
All prompts are context-aware: they receive the user's knowledge base
context dict before generating any response, making every call
"remember" the user's history, targets, and inventory.

Models used:
  - Food image analysis : meta-llama/llama-4-scout-17b-16e-instruct  (vision)
  - Meal plan / text    : llama-3.3-70b-versatile                    (text, faster + cheaper)
"""

import json
from groq import Groq
from app.config import settings

client = Groq(api_key=settings.GROQ_API_KEY)

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
TEXT_MODEL   = "llama-3.3-70b-versatile"


# ─────────────────────────────────────────────
# Helper: clean JSON out of model response
# ─────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        # parts[1] is the content between first and second ```
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ─────────────────────────────────────────────
# 1. Food Image / Text Analysis
# ─────────────────────────────────────────────

async def analyze_food(
    image_base64: str | None,
    description: str,
    context: dict,
) -> dict:
    """
    Analyze a meal from image and/or text description.
    Context is used to improve accuracy (e.g. dietary restrictions).
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
- confidence: 0.0–1.0 (how clearly visible/described the food is)
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
            {"role": "user",   "content": user_content if image_base64 else text_input},
        ],
        max_tokens=1000,
        temperature=0.1,
    )

    return _parse_json(response.choices[0].message.content)


# ─────────────────────────────────────────────
# 2. Meal Plan Generator
# Uses full context including binge recovery flag
# ─────────────────────────────────────────────

async def generate_meal_plan(context: dict, trigger: str = "daily_routine") -> dict:
    """
    Generate a meal plan for the rest of today (or tomorrow if evening).
    Trigger can be: daily_routine | binge_recovery | inventory_expiry | user_request
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

    # Build inventory string for prompt
    inventory_str = (
        "\n".join(f"- {i['name']} ({i.get('quantity','?')})" for i in inventory)
        if inventory else "No inventory tracked yet"
    )
    expiring_str = ", ".join(expiring_soon) if expiring_soon else "none"

    # Build week history string
    week_str = (
        "\n".join(
            f"- {d['date']}: {d['calories']} kcal "
            f"({'OVER' if d['vs_target']>0 else 'under'} by {abs(d['vs_target'])} kcal)"
            f"{' [BINGE]' if d['is_binge_day'] else ''}"
            for d in week_summary
        ) if week_summary else "No history yet"
    )

    # Binge recovery instruction
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
    result["trigger"] = trigger
    result["binge_recovery"] = binge_mode
    return result


# ─────────────────────────────────────────────
# 3. Inventory-aware meal suggestion
# Quick call — just uses inventory + restrictions
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

    return _parse_json(response.choices[0].message.content)