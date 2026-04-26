from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.limiter import limiter
from app.models.models import User
from app.core.dependencies import get_current_user
from app.services.ai_service import generate_meal_plan, suggest_from_inventory
from app.agents.analyser_agent import analyze_food_agentic
from app.services.usda_service import validate_food
from app.services.kb_service import save_log, get_user_context

router = APIRouter(prefix="/meal", tags=["meal"])


# ─── Request / Response models ───────────────

class LogMealRequest(BaseModel):
    # user_id comes from JWT token — not required in body
    image_base64: str | None = None
    description: str = ""
    meal_type: str = "lunch"
    image_url: str | None = None  # S3 URL after iOS uploads image

class MealPlanRequest(BaseModel):
    # user_id comes from JWT token — not required in body
    trigger: str = "user_request"
    # "daily_routine" | "binge_recovery" | "inventory_expiry" | "user_request"

class InventorySuggestRequest(BaseModel):
    pass  # user_id comes from JWT token — no body fields needed'''


# ─── Endpoints ───────────────────────────────

@router.post("/log")
@limiter.limit("20/minute")
async def log_meal(request: Request, req: LogMealRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Main meal logging endpoint.
    Accepts image (base64) and/or text description.
    Returns AI macros, USDA validation, and updated daily totals.
    """
    if not req.image_base64 and not req.description:
        raise HTTPException(400, "Provide at least an image or a description")

    # 1. Get user context (needed for personalised AI prompt)
    context = await get_user_context(db, current_user.id)

    # 2. AI analysis
    try:
        ai_result = await analyze_food_agentic(req.image_base64, req.description, context)
    except Exception as e:
        raise HTTPException(502, f"AI analysis failed: {str(e)}")

    # 3. USDA validation on the primary food item
    usda_result = {}
    food_items  = ai_result.get("food_items", [])
    if food_items:
        try:
            usda_result = await validate_food(
                food_items[0]["name"],
                food_items[0].get("calories", 0)
            )
        except Exception:
            usda_result = {"matched": False, "error": "USDA lookup failed"}

    # 4. Save to knowledge base
    log_id = await save_log(
        db=db,
        user_id=current_user.id,
        meal_type=req.meal_type,
        source="image" if req.image_base64 else "text",
        ai_result=ai_result,
        usda_result=usda_result,
        user_description=req.description,
        image_url=req.image_url,
    )

    # 5. Refresh context to get updated daily totals
    updated_context = await get_user_context(db, current_user.id)

    return {
        "log_id":          log_id,
        "food_items":      ai_result.get("food_items", []),
        "total_macros":    ai_result.get("total", {}),
        "ai_confidence":   ai_result.get("confidence", 0),
        "ai_notes":        ai_result.get("notes", ""),
        "usda_validation": usda_result,
        "daily_totals":    updated_context["today_totals"],
        "remaining_calories":  updated_context["remaining_calories"],
        "remaining_protein_g": updated_context["remaining_protein_g"],
        "meals_logged_today":  updated_context["meals_logged_today"],
        "binge_alert":     updated_context["binge_recovery_mode"],
    }


@router.post("/plan")
@limiter.limit("10/minute")
async def get_meal_plan(request: Request, req: MealPlanRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Generate a personalised meal plan for remaining meals today.
    Automatically uses binge-recovery mode if binge was detected.
    """
    context = await get_user_context(db, current_user.id)

    # Auto-upgrade trigger if binge detected
    trigger = req.trigger
    if context.get("binge_recovery_mode") and trigger == "user_request":
        trigger = "binge_recovery"

    try:
        plan = await generate_meal_plan(context, trigger=trigger)
    except Exception as e:
        raise HTTPException(502, f"Meal plan generation failed: {str(e)}")

    return plan


@router.post("/suggest-from-inventory")
async def suggest_meals(req: InventorySuggestRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Quick meal suggestions based purely on what's in the user's inventory.
    Lightweight — no weekly history needed.
    """
    context = await get_user_context(db, current_user.id)
    return await suggest_from_inventory(context)


@router.get("/context/{user_id}")
async def get_context(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Debug endpoint — returns the full knowledge base context for a user.
    Useful during development to verify history is building correctly.
    Remove or auth-gate before production.
    """
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")
    return await get_user_context(db, user_id)
