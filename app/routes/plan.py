"""
Plan Routes
───────────
POST /plan/generate          — generate + optionally save a meal plan
POST /plan/accept/{plan_id}  — user accepts a suggested plan (marks it active)
GET  /plan/active/{user_id}  — fetch today's active plan (for home screen)
POST /plan/revise-week       — proactively revise rest of week after binge

The weekly revision is the core differentiator:
  - Looks at how many kcal over/under the user has been this week
  - Calculates a weekly deficit/surplus to redistribute
  - Generates revised plans for each remaining day of the week
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import date, timedelta
import uuid

from app.db import get_db
from app.models.models import MealPlan, DailySummary, User
from app.services.ai_service import generate_meal_plan
from app.services.kb_service import get_user_context
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/plan", tags=["plan"])


class GeneratePlanRequest(BaseModel):
    trigger: str = "user_request"
    save: bool = True   # if True, persist to meal_plans table


# ─────────────────────────────────────────────
# Generate + optionally save a plan
# ─────────────────────────────────────────────

@router.post("/generate")
async def generate_plan(
    req: GeneratePlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    context = await get_user_context(db, current_user.id)

    trigger = req.trigger
    if context.get("binge_recovery_mode") and trigger == "user_request":
        trigger = "binge_recovery"

    plan_data = await generate_meal_plan(context, trigger=trigger)

    plan_id = None
    if req.save:
        # Deactivate any existing plan for today
        today = date.today()
        existing = await db.execute(
            select(MealPlan).where(
                and_(
                    MealPlan.user_id   == current_user.id,
                    MealPlan.plan_date == today,
                    MealPlan.is_active == True,
                )
            )
        )
        for old_plan in existing.scalars().all():
            old_plan.is_active = False

        new_plan = MealPlan(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            plan_date=today,
            plan=plan_data,
            trigger=trigger,
            is_active=False,   # not active until user accepts
        )
        db.add(new_plan)
        await db.commit()
        await db.refresh(new_plan)
        plan_id = new_plan.id

    return {**plan_data, "plan_id": plan_id}


# ─────────────────────────────────────────────
# Accept a plan (user taps "Follow this plan")
# ─────────────────────────────────────────────

@router.post("/accept/{plan_id}")
async def accept_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    plan = await db.get(MealPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    if plan.user_id != current_user.id:
        raise HTTPException(403, "Not authorised")

    plan.is_active = True
    await db.commit()
    return {"accepted": True, "plan_id": plan_id}


# ─────────────────────────────────────────────
# Get today's active plan
# ─────────────────────────────────────────────

@router.get("/active/{user_id}")
async def get_active_plan(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")

    today = date.today()
    result = await db.execute(
        select(MealPlan).where(
            and_(
                MealPlan.user_id   == user_id,
                MealPlan.plan_date == today,
                MealPlan.is_active == True,
            )
        ).order_by(MealPlan.created_at.desc())
    )
    plan = result.scalar_one_or_none()
    if not plan:
        return {"active_plan": None}

    return {"active_plan": {**plan.plan, "plan_id": plan.id, "plan_date": str(plan.plan_date)}}


# ─────────────────────────────────────────────
# Weekly revision
# The core differentiator — call after a binge day
# ─────────────────────────────────────────────

@router.post("/revise-week")
async def revise_week(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Looks at calories consumed Mon–today, calculates how far over/under
    the weekly target the user is, then generates revised plans for each
    remaining day of the week to rebalance — without starving the user.

    iOS should call this automatically when is_binge_day becomes true.
    """
    today      = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    days_left  = 6 - today.weekday()                       # days remaining in week

    if days_left == 0:
        return {"message": "No remaining days this week to revise", "plans": []}

    # Fetch this week's summaries
    result = await db.execute(
        select(DailySummary).where(
            and_(
                DailySummary.user_id  == current_user.id,
                DailySummary.log_date >= week_start,
                DailySummary.log_date <= today,
            )
        )
    )
    summaries = result.scalars().all()

    # Calculate weekly surplus/deficit so far
    days_elapsed       = today.weekday() + 1
    weekly_target      = current_user.calorie_target * days_elapsed
    calories_consumed  = sum(s.total_calories for s in summaries)
    weekly_surplus     = calories_consumed - weekly_target

    # Distribute surplus evenly across remaining days
    # Cap adjustment at ±500 kcal/day so it's not extreme
    daily_adjustment   = max(-500, min(500, -(weekly_surplus / max(days_left, 1))))
    adjusted_target    = max(1200, current_user.calorie_target + daily_adjustment)

    # Build context with modified calorie target for revision
    base_context = await get_user_context(db, current_user.id)

    revised_plans = []
    for i in range(1, days_left + 1):
        plan_date = today + timedelta(days=i)

        # Temporarily override calorie target for this generation
        revision_context = {
            **base_context,
            "calorie_target":      adjusted_target,
            "remaining_calories":  adjusted_target,
            "binge_recovery_mode": True,
            "today_meals":         [],   # future day — no meals yet
        }

        plan_data = await generate_meal_plan(
            revision_context,
            trigger="binge_recovery"
        )

        # Deactivate old plan for this day if exists
        old = await db.execute(
            select(MealPlan).where(
                and_(
                    MealPlan.user_id   == current_user.id,
                    MealPlan.plan_date == plan_date,
                )
            )
        )
        for op in old.scalars().all():
            op.is_active = False

        new_plan = MealPlan(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            plan_date=plan_date,
            plan=plan_data,
            trigger="binge_recovery",
            is_active=True,
        )
        db.add(new_plan)
        revised_plans.append({
            "date":            str(plan_date),
            "adjusted_target": round(adjusted_target),
            "plan":            plan_data,
        })

    await db.commit()

    return {
        "weekly_surplus_kcal":  round(weekly_surplus),
        "daily_adjustment":     round(daily_adjustment),
        "adjusted_daily_target": round(adjusted_target),
        "days_revised":         days_left,
        "plans":                revised_plans,
        "message": (
            f"Your week has been rebalanced. "
            f"{'Reducing' if daily_adjustment < 0 else 'Increasing'} daily target by "
            f"{abs(round(daily_adjustment))} kcal for the next {days_left} days."
        ),
    }