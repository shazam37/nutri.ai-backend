from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from app.db import get_db
from app.limiter import limiter
from app.models.models import User
from app.core.dependencies import get_current_user
from app.services.ai_service import (
    generate_meal_plan,
    suggest_from_inventory,
    suggest_what_to_eat_now,
)
from app.agents.analyser_agent import analyze_food_agentic
from app.services.usda_service import validate_food
from app.services.kb_service import save_log, get_user_context

router = APIRouter(prefix="/meal", tags=["meal"])


class LogMealRequest(BaseModel):
    image_base64: str | None = None
    description: str = ""
    meal_type: str = "lunch"
    image_url: str | None = None


class MealPlanRequest(BaseModel):
    trigger: str = "user_request"


class InventorySuggestRequest(BaseModel):
    pass


class MacroFoodItem(BaseModel):
    name: str
    quantity: str = "1 serving"
    calories: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0


class ReviewedLogRequest(BaseModel):
    food_items: list[MacroFoodItem]
    meal_type: str = "lunch"
    total_macros: dict[str, float] | None = None
    micros: dict[str, float] | None = None
    ai_confidence: float = 1.0
    ai_notes: str = "Reviewed and confirmed by user"
    usda_validation: dict | None = None
    description: str = ""
    image_url: str | None = None
    source: Literal["image", "text", "quick_form"] = "quick_form"


class WhatCanIEatRequest(BaseModel):
    meal_type: str | None = None
    max_options: int = 3


def _total_from_items(items: list[MacroFoodItem]) -> dict:
    return {
        "calories": sum(i.calories for i in items),
        "protein_g": sum(i.protein_g for i in items),
        "carbs_g": sum(i.carbs_g for i in items),
        "fat_g": sum(i.fat_g for i in items),
        "fiber_g": sum(i.fiber_g for i in items),
    }


def _normalise_total(total: dict | None, items: list[MacroFoodItem]) -> dict:
    out = dict(total or _total_from_items(items))
    for field in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g"):
        out[field] = float(out.get(field, 0) or 0)
    return out


async def _run_meal_analysis(req: LogMealRequest, db: AsyncSession, user_id: str) -> dict:
    if not req.image_base64 and not req.description:
        raise HTTPException(400, "Provide at least an image or a description")

    context = await get_user_context(db, user_id)

    try:
        ai_result = await analyze_food_agentic(req.image_base64, req.description, context)
    except Exception as e:
        raise HTTPException(502, f"AI analysis failed: {str(e)}")

    usda_result = {}
    food_items = ai_result.get("food_items", [])
    if food_items:
        try:
            usda_result = await validate_food(
                food_items[0]["name"],
                food_items[0].get("calories", 0),
            )
        except Exception:
            usda_result = {"matched": False, "error": "USDA lookup failed"}

    return {"ai_result": ai_result, "usda_result": usda_result}


@router.post("/analyze")
@limiter.limit("20/minute")
async def analyze_meal_for_review(
    request: Request,
    req: LogMealRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Analyse a meal without saving it.
    Android should show this result on a review/edit screen, then call
    /meal/log-reviewed after the user confirms or corrects the result.
    """
    analysis = await _run_meal_analysis(req, db, current_user.id)
    ai_result = analysis["ai_result"]
    usda_result = analysis["usda_result"]
    source = "image" if req.image_base64 else "text"

    return {
        "review_required": True,
        "food_items": ai_result.get("food_items", []),
        "total_macros": ai_result.get("total", {}),
        "micros": ai_result.get("micros", {}),
        "ai_confidence": ai_result.get("confidence", 0),
        "ai_notes": ai_result.get("notes", ""),
        "agent_steps": ai_result.get("agent_steps", []),
        "agent_invoked": ai_result.get("agent_invoked", False),
        "usda_validation": usda_result,
        "suggested_log_payload": {
            "food_items": ai_result.get("food_items", []),
            "meal_type": req.meal_type,
            "total_macros": ai_result.get("total", {}),
            "micros": ai_result.get("micros", {}),
            "ai_confidence": ai_result.get("confidence", 0),
            "ai_notes": ai_result.get("notes", ""),
            "usda_validation": usda_result,
            "description": req.description,
            "image_url": req.image_url,
            "source": source,
        },
    }


@router.post("/log-reviewed")
async def log_reviewed_meal(
    req: ReviewedLogRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Save a user-reviewed meal result.
    This supports the POC review/edit flow without changing /meal/log.
    """
    if not req.food_items:
        raise HTTPException(400, "Provide at least one food item")

    total = _normalise_total(req.total_macros, req.food_items)
    ai_result = {
        "food_items": [item.model_dump() for item in req.food_items],
        "total": total,
        "micros": req.micros or {},
        "confidence": max(0.0, min(1.0, req.ai_confidence)),
        "notes": req.ai_notes,
        "reviewed_by_user": True,
    }

    log_id = await save_log(
        db=db,
        user_id=current_user.id,
        meal_type=req.meal_type,
        source=req.source,
        ai_result=ai_result,
        usda_result=req.usda_validation or {"matched": False, "reviewed": True},
        user_description=req.description,
        image_url=req.image_url,
    )

    updated_context = await get_user_context(db, current_user.id)

    return {
        "log_id": log_id,
        "food_items": ai_result["food_items"],
        "total_macros": total,
        "daily_totals": updated_context["today_totals"],
        "remaining_calories": updated_context["remaining_calories"],
        "remaining_protein_g": updated_context["remaining_protein_g"],
        "meals_logged_today": updated_context["meals_logged_today"],
        "binge_alert": updated_context["binge_recovery_mode"],
        "reviewed": True,
    }


@router.post("/log")
@limiter.limit("20/minute")
async def log_meal(
    request: Request,
    req: LogMealRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Existing one-shot meal logging endpoint.
    Kept intact for current clients: analyse, validate, save, return totals.
    """
    analysis = await _run_meal_analysis(req, db, current_user.id)
    ai_result = analysis["ai_result"]
    usda_result = analysis["usda_result"]

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

    updated_context = await get_user_context(db, current_user.id)

    return {
        "log_id": log_id,
        "food_items": ai_result.get("food_items", []),
        "total_macros": ai_result.get("total", {}),
        "ai_confidence": ai_result.get("confidence", 0),
        "ai_notes": ai_result.get("notes", ""),
        "usda_validation": usda_result,
        "daily_totals": updated_context["today_totals"],
        "remaining_calories": updated_context["remaining_calories"],
        "remaining_protein_g": updated_context["remaining_protein_g"],
        "meals_logged_today": updated_context["meals_logged_today"],
        "binge_alert": updated_context["binge_recovery_mode"],
    }


@router.post("/plan")
@limiter.limit("10/minute")
async def get_meal_plan(
    request: Request,
    req: MealPlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a personalised meal plan for remaining meals today.
    Automatically uses binge-recovery mode if binge was detected.
    """
    context = await get_user_context(db, current_user.id)

    trigger = req.trigger
    if context.get("binge_recovery_mode") and trigger == "user_request":
        trigger = "binge_recovery"

    try:
        plan = await generate_meal_plan(context, trigger=trigger)
    except Exception as e:
        raise HTTPException(502, f"Meal plan generation failed: {str(e)}")

    return plan


@router.post("/suggest-from-inventory")
async def suggest_meals(
    req: InventorySuggestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Quick meal suggestions based purely on what's in the user's inventory.
    Lightweight: no weekly history needed.
    """
    context = await get_user_context(db, current_user.id)
    return await suggest_from_inventory(context)


@router.post("/what-can-i-eat-now")
@limiter.limit("10/minute")
async def what_can_i_eat_now(
    request: Request,
    req: WhatCanIEatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Suggest meals/snacks that fit the user's live budget and inventory.
    This powers the Android home-screen "What can I eat now?" action.
    """
    context = await get_user_context(db, current_user.id)
    try:
        suggestions = await suggest_what_to_eat_now(
            context,
            meal_type=req.meal_type,
            max_options=req.max_options,
        )
    except Exception as e:
        raise HTTPException(502, f"Suggestion generation failed: {str(e)}")

    return {
        **suggestions,
        "remaining_calories": context["remaining_calories"],
        "remaining_protein_g": context["remaining_protein_g"],
        "expiring_soon": context["expiring_soon"],
        "inventory_items": context["inventory_items"],
    }


@router.get("/context/{user_id}")
async def get_context(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Debug endpoint: returns the full knowledge base context for a user.
    Useful during development to verify history is building correctly.
    """
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")
    return await get_user_context(db, user_id)
