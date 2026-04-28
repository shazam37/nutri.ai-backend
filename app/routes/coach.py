from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.models import User
from app.core.dependencies import get_current_user
from app.services.kb_service import get_user_context

router = APIRouter(prefix="/coach", tags=["coach"])


def _progress_pct(consumed: float, target: float) -> int:
    if target <= 0:
        return 0
    return min(100, round((consumed / target) * 100))


def _build_today_card(context: dict) -> dict:
    today = context.get("today_totals", {})
    calories = float(today.get("calories", 0) or 0)
    protein = float(today.get("protein_g", 0) or 0)
    calorie_target = float(context.get("calorie_target", 2000) or 2000)
    protein_target = float(context.get("protein_target_g", 150) or 150)
    remaining_calories = float(context.get("remaining_calories", calorie_target) or 0)
    remaining_protein = float(context.get("remaining_protein_g", protein_target) or 0)
    meals_logged = int(context.get("meals_logged_today", 0) or 0)
    expiring = context.get("expiring_soon", [])
    inventory = context.get("inventory_items", [])
    binge_mode = bool(context.get("binge_recovery_mode", False))

    if binge_mode:
        return {
            "type": "binge_recovery",
            "priority": "high",
            "title": "Gentle reset for today",
            "message": (
                "Your week has a high-calorie day. Keep today satisfying, "
                "protein-forward, and a little lighter."
            ),
            "action": {
                "label": "Revise week",
                "method": "POST",
                "endpoint": "/api/v1/plan/revise-week",
            },
        }

    if expiring:
        items = ", ".join(expiring[:2])
        return {
            "type": "inventory_expiry",
            "priority": "high",
            "title": "Use expiring food first",
            "message": f"{items} should be used soon. I can suggest a meal around it.",
            "action": {
                "label": "What can I eat now?",
                "method": "POST",
                "endpoint": "/api/v1/meal/what-can-i-eat-now",
            },
        }

    if meals_logged == 0:
        return {
            "type": "start_day",
            "priority": "medium",
            "title": "Start with a simple plan",
            "message": "Nothing logged yet today. Generate a plan or log your first meal.",
            "action": {
                "label": "Generate plan",
                "method": "POST",
                "endpoint": "/api/v1/plan/generate",
            },
        }

    if remaining_protein >= 35:
        return {
            "type": "protein_gap",
            "priority": "medium",
            "title": "Protein gap to close",
            "message": (
                f"You still have about {round(remaining_protein)}g protein left. "
                "Pick a high-protein meal or snack next."
            ),
            "action": {
                "label": "Find protein option",
                "method": "POST",
                "endpoint": "/api/v1/meal/what-can-i-eat-now",
            },
        }

    if remaining_calories <= 250:
        return {
            "type": "light_finish",
            "priority": "low",
            "title": "Light finish today",
            "message": "You are close to today's calorie target. Keep the rest light and hydrating.",
            "action": {
                "label": "Log water",
                "method": "POST",
                "endpoint": "/api/v1/utils/water",
            },
        }

    if inventory:
        return {
            "type": "inventory_suggestion",
            "priority": "medium",
            "title": "Cook from your kitchen",
            "message": (
                f"You have {round(remaining_calories)} kcal left. "
                "I can suggest something from your inventory."
            ),
            "action": {
                "label": "What can I eat now?",
                "method": "POST",
                "endpoint": "/api/v1/meal/what-can-i-eat-now",
            },
        }

    return {
        "type": "steady_progress",
        "priority": "low",
        "title": "You are on track",
        "message": (
            f"{round(remaining_calories)} kcal left today. "
            "Log your next meal or ask for a suggestion."
        ),
        "action": {
            "label": "Log meal",
            "method": "POST",
            "endpoint": "/api/v1/meal/analyze",
        },
    }


@router.get("/today")
async def get_today_coach_card(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deterministic daily coach card for the Android home screen.
    Cheap, fast, and based on the same knowledge context as the AI features.
    """
    context = await get_user_context(db, current_user.id)
    card = _build_today_card(context)
    today = context["today_totals"]

    return {
        "card": card,
        "progress": {
            "calories_pct": _progress_pct(today.get("calories", 0), context["calorie_target"]),
            "protein_pct": _progress_pct(today.get("protein_g", 0), context["protein_target_g"]),
            "meals_logged": context["meals_logged_today"],
            "remaining_calories": context["remaining_calories"],
            "remaining_protein_g": context["remaining_protein_g"],
        },
        "signals": {
            "binge_recovery_mode": context["binge_recovery_mode"],
            "binge_days_count": context["binge_days_count"],
            "expiring_soon": context["expiring_soon"],
            "inventory_count": len(context["inventory_items"]),
        },
    }
