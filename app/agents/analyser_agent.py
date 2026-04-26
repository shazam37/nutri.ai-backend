"""
Agent 2 — Multi-step Food Analyser Agent
─────────────────────────────────────────
This agent wraps the existing analyze_food() function in ai_service.py.
It adds a decision loop: if confidence is too low, it autonomously
takes extra steps to improve accuracy before returning to the caller.

HOW IT INTEGRATES:
  - meal.py calls analyze_food() today
  - We add one function here: analyze_food_agentic()
  - ai_service.py will re-export it so meal.py import doesn't change
  - Existing flow is completely untouched for high-confidence results

AGENT LOOP:
  Step 1: Call existing analyze_food() — get initial result
  Step 2: Check confidence score
    → If >= 0.75: return immediately (single step, same as today)
    → If < 0.75:  agent kicks in
  Step 3: Search USDA for primary food item (tool call 1)
  Step 4: If USDA matched: re-prompt Groq with USDA calibration data (tool call 2)
  Step 5: Reconcile both estimates, return best result with audit trail
  Step 6: If USDA didn't match: try rephrasing the food name and retry (tool call 3)

Max steps: 3 tool calls. Never infinite loops.
"""

import logging

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.75
MAX_AGENT_STEPS = 3


async def analyze_food_agentic(
    image_base64: str | None,
    description: str,
    context: dict,
) -> dict:
    """
    Drop-in replacement for analyze_food() with agentic retry loop.
    Returns same response shape as analyze_food() plus agent metadata.
    """

    from app.services.ai_service import analyze_food
    from app.services.usda_service import validate_food

    steps_taken = []

    # ── Step 1: Initial analysis (same as existing flow) ──────────────
    logger.info("[Analyser Agent] Step 1: Initial food analysis")
    result = await analyze_food(image_base64, description, context)
    steps_taken.append({
        "step": 1,
        "action": "initial_analysis",
        "confidence": result.get("confidence", 0),
        "items_found": len(result.get("food_items", [])),
    })

    confidence = result.get("confidence", 0)

    # ── Step 2: Agent decision point ──────────────────────────────────
    if confidence >= CONFIDENCE_THRESHOLD:
        logger.info(f"[Analyser Agent] Confidence {confidence:.2f} ≥ threshold. Done in 1 step.")
        result["agent_steps"] = steps_taken
        result["agent_invoked"] = False
        return result

    logger.info(f"[Analyser Agent] Confidence {confidence:.2f} < {CONFIDENCE_THRESHOLD}. Invoking agent loop.")

    # ── Step 3: USDA lookup as tool call ──────────────────────────────
    food_items = result.get("food_items", [])
    primary_name = food_items[0]["name"] if food_items else description
    primary_calories = food_items[0].get("calories", 0) if food_items else 0

    logger.info(f"[Analyser Agent] Step 2: USDA lookup for '{primary_name}'")
    usda_result = await validate_food(primary_name, primary_calories)
    steps_taken.append({
        "step": 2,
        "action": "usda_lookup",
        "query": primary_name,
        "matched": usda_result.get("matched", False),
        "usda_name": usda_result.get("usda_name"),
    })

    # ── Step 4a: USDA matched — re-prompt with calibration data ───────
    if usda_result.get("matched"):
        usda_name     = usda_result["usda_name"]
        usda_cal_100g = usda_result["usda_calories_per_100g"]
        accuracy_delta = usda_result.get("accuracy_delta", 0) or 0

        logger.info(f"[Analyser Agent] Step 3: Re-prompting with USDA calibration (delta={accuracy_delta:.2f})")

        calibrated_description = f"""{description if description else f'The food shown is {primary_name}'}

USDA Reference Data (use this to calibrate your portion estimate):
- Verified food name: {usda_name}
- Calories per 100g (USDA): {usda_cal_100g} kcal
- Previous AI estimate was {abs(accuracy_delta * 100):.0f}% {'over' if accuracy_delta and primary_calories > usda_cal_100g else 'under'} the USDA value.

Re-estimate the portion size and macros using this reference.
Be precise about the quantity based on what you can see or what was described."""

        refined_result = await analyze_food(image_base64, calibrated_description, context)
        steps_taken.append({
            "step": 3,
            "action": "usda_calibrated_reanalysis",
            "confidence_before": confidence,
            "confidence_after":  refined_result.get("confidence", 0),
            "usda_name":         usda_name,
        })

        # Use refined result if it has higher or equal confidence
        if refined_result.get("confidence", 0) >= confidence:
            refined_result["agent_steps"]    = steps_taken
            refined_result["agent_invoked"]  = True
            refined_result["usda_calibrated"] = True
            refined_result["usda_reference"] = {
                "name":            usda_name,
                "calories_per_100g": usda_cal_100g,
                "accuracy_delta":  accuracy_delta,
                "flag":            usda_result.get("flag", "unverified"),
            }
            logger.info(f"[Analyser Agent] Refined confidence: {refined_result['confidence']:.2f}. Done.")
            return refined_result
        else:
            # Refined result was worse — keep original but attach USDA data
            logger.info("[Analyser Agent] Refined result was lower confidence. Keeping original + USDA ref.")
            result["agent_steps"]    = steps_taken
            result["agent_invoked"]  = True
            result["usda_calibrated"] = False
            result["usda_reference"] = {
                "name":            usda_name,
                "calories_per_100g": usda_cal_100g,
                "accuracy_delta":  accuracy_delta,
                "flag":            usda_result.get("flag", "unverified"),
            }
            return result

    # ── Step 4b: USDA didn't match — try rephrased food name ──────────
    else:
        logger.info(f"[Analyser Agent] USDA no match for '{primary_name}'. Trying simplified name.")

        # Ask AI to give us a simpler, more generic food name for USDA search
        simplified_description = (
            f"Identify just the primary base food in: '{primary_name}'. "
            f"Use a simple generic name (e.g. 'chicken breast' not 'grilled spicy chicken'). "
            f"Context: {description}"
        )

        # Re-analyse with instruction to simplify
        simplified_result = await analyze_food(None, simplified_description, context)
        simplified_items = simplified_result.get("food_items", [])

        steps_taken.append({
            "step": 3,
            "action": "simplified_name_retry",
            "original_name": primary_name,
            "simplified_name": simplified_items[0]["name"] if simplified_items else "unknown",
        })

        if simplified_items:
            new_name = simplified_items[0]["name"]
            new_calories = simplified_items[0].get("calories", 0)

            # Try USDA again with simplified name
            usda_retry = await validate_food(new_name, new_calories)
            if usda_retry.get("matched"):
                result["usda_reference"] = {
                    "name":              usda_retry["usda_name"],
                    "calories_per_100g": usda_retry["usda_calories_per_100g"],
                    "accuracy_delta":    usda_retry.get("accuracy_delta"),
                    "flag":              usda_retry.get("flag", "unverified"),
                }

        # Return original result — we tried our best
        result["agent_steps"]    = steps_taken
        result["agent_invoked"]  = True
        result["usda_calibrated"] = False
        result["low_confidence_warning"] = (
            "Confidence remains low. Consider adding a text description to improve accuracy."
        )
        logger.info("[Analyser Agent] Could not resolve low confidence. Returning best estimate.")
        return result