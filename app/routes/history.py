"""
History Routes
──────────────
GET /history/{user_id}/daily?days=7    — daily summary trend (macro rings + calorie chart)
GET /history/{user_id}/logs?date=today — all food logs for a specific date
DELETE /history/log/{log_id}           — delete a food log + revert daily summary
PATCH  /history/log/{log_id}           — edit a food log entry
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import date, timedelta

from app.db import get_db
from app.models.models import FoodLog, DailySummary, User
from app.routes.auth import get_current_user

router = APIRouter(prefix="/history", tags=["history"])


# ─────────────────────────────────────────────
# Daily summary trend
# Used by iOS for: weekly calorie chart, macro trend, streak tracking
# ─────────────────────────────────────────────

@router.get("/{user_id}/daily")
async def get_daily_history(
    user_id: str,
    days: int = Query(default=7, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")

    today    = date.today()
    from_date = today - timedelta(days=days - 1)

    result = await db.execute(
        select(DailySummary).where(
            and_(
                DailySummary.user_id  == user_id,
                DailySummary.log_date >= from_date,
                DailySummary.log_date <= today,
            )
        ).order_by(DailySummary.log_date.asc())
    )
    summaries = result.scalars().all()

    # Build a full date range (fill missing days with zeros)
    summary_by_date = {s.log_date: s for s in summaries}
    user = await db.get(User, user_id)

    daily = []
    for i in range(days):
        d = from_date + timedelta(days=i)
        s = summary_by_date.get(d)
        daily.append({
            "date":           str(d),
            "calories":       round(s.total_calories,  1) if s else 0,
            "protein_g":      round(s.total_protein_g, 1) if s else 0,
            "carbs_g":        round(s.total_carbs_g,   1) if s else 0,
            "fat_g":          round(s.total_fat_g,     1) if s else 0,
            "fiber_g":        round(s.total_fiber_g,   1) if s else 0,
            "meals_logged":   s.meals_logged if s else 0,
            "is_binge_day":   s.is_binge_day if s else False,
            "target_calories": user.calorie_target if user else 2000,
            "vs_target":      round(s.total_calories - user.calorie_target, 1) if (s and user) else 0,
        })

    # Streak: consecutive days with at least 1 meal logged
    streak = 0
    for d in reversed(daily):
        if d["meals_logged"] > 0:
            streak += 1
        else:
            break

    return {
        "days":   daily,
        "streak": streak,
        "period": {"from": str(from_date), "to": str(today)},
    }


# ─────────────────────────────────────────────
# Food logs for a specific date
# Used by iOS for: meal history list screen
# ─────────────────────────────────────────────

@router.get("/{user_id}/logs")
async def get_logs_for_date(
    user_id: str,
    date_str: str = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")

    log_date = date.fromisoformat(date_str) if date_str else date.today()

    result = await db.execute(
        select(FoodLog).where(
            and_(FoodLog.user_id == user_id, FoodLog.log_date == log_date)
        ).order_by(FoodLog.logged_at.asc())
    )
    logs = result.scalars().all()

    return {
        "date": str(log_date),
        "logs": [
            {
                "log_id":       l.id,
                "meal_type":    l.meal_type,
                "logged_at":    l.logged_at.isoformat(),
                "source":       l.source,
                "description":  l.user_description,
                "image_url":    l.image_url,
                "food_items":   l.ai_response.get("food_items", []),
                "macros": {
                    "calories":  round(l.calories,  1),
                    "protein_g": round(l.protein_g, 1),
                    "carbs_g":   round(l.carbs_g,   1),
                    "fat_g":     round(l.fat_g,     1),
                    "fiber_g":   round(l.fiber_g,   1),
                },
                "ai_confidence":   l.ai_confidence,
                "usda_validation": l.usda_validation,
            }
            for l in logs
        ],
        "total_logs": len(logs),
    }


# ─────────────────────────────────────────────
# Delete a food log
# Subtracts macros from DailySummary
# ─────────────────────────────────────────────

@router.delete("/log/{log_id}")
async def delete_log(
    log_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    log = await db.get(FoodLog, log_id)
    if not log:
        raise HTTPException(404, "Log not found")
    if log.user_id != current_user.id:
        raise HTTPException(403, "Not authorised")

    # Revert the daily summary
    result = await db.execute(
        select(DailySummary).where(
            and_(
                DailySummary.user_id  == log.user_id,
                DailySummary.log_date == log.log_date,
            )
        )
    )
    summary = result.scalar_one_or_none()
    if summary:
        summary.total_calories  = max(0, summary.total_calories  - log.calories)
        summary.total_protein_g = max(0, summary.total_protein_g - log.protein_g)
        summary.total_carbs_g   = max(0, summary.total_carbs_g   - log.carbs_g)
        summary.total_fat_g     = max(0, summary.total_fat_g     - log.fat_g)
        summary.total_fiber_g   = max(0, summary.total_fiber_g   - log.fiber_g)
        summary.meals_logged    = max(0, summary.meals_logged    - 1)

        user = await db.get(User, log.user_id)
        if user:
            summary.remaining_calories  = max(0, user.calorie_target   - summary.total_calories)
            summary.remaining_protein_g = max(0, user.protein_target_g - summary.total_protein_g)
            summary.is_binge_day        = summary.total_calories > (user.calorie_target * 1.3)

    await db.delete(log)
    await db.commit()
    return {"deleted": True, "log_id": log_id}


# ─────────────────────────────────────────────
# Edit a food log
# Adjusts macros delta in DailySummary
# ─────────────────────────────────────────────

class EditLogRequest(BaseModel):
    calories:  float | None = None
    protein_g: float | None = None
    carbs_g:   float | None = None
    fat_g:     float | None = None
    fiber_g:   float | None = None
    meal_type: str   | None = None


@router.patch("/log/{log_id}")
async def edit_log(
    log_id: str,
    req: EditLogRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    log = await db.get(FoodLog, log_id)
    if not log:
        raise HTTPException(404, "Log not found")
    if log.user_id != current_user.id:
        raise HTTPException(403, "Not authorised")

    result = await db.execute(
        select(DailySummary).where(
            and_(
                DailySummary.user_id  == log.user_id,
                DailySummary.log_date == log.log_date,
            )
        )
    )
    summary = result.scalar_one_or_none()

    # Calculate deltas and apply
    # Map log field name → summary field name
    field_map = {
        "calories":  "total_calories",
        "protein_g": "total_protein_g",
        "carbs_g":   "total_carbs_g",
        "fat_g":     "total_fat_g",
        "fiber_g":   "total_fiber_g",
    }

    def apply(field: str, new_val: float | None):
        if new_val is None:
            return
        old_val = getattr(log, field)
        delta   = new_val - old_val
        setattr(log, field, new_val)
        if summary:
            summary_field = field_map[field]
            current = getattr(summary, summary_field)
            setattr(summary, summary_field, max(0, current + delta))

    apply("calories",  req.calories)
    apply("protein_g", req.protein_g)
    apply("carbs_g",   req.carbs_g)
    apply("fat_g",     req.fat_g)
    apply("fiber_g",   req.fiber_g)

    if req.meal_type:
        log.meal_type = req.meal_type

    # Recalculate remaining
    if summary:
        user = await db.get(User, log.user_id)
        if user:
            summary.remaining_calories  = max(0, user.calorie_target   - summary.total_calories)
            summary.remaining_protein_g = max(0, user.protein_target_g - summary.total_protein_g)
            summary.is_binge_day        = summary.total_calories > (user.calorie_target * 1.3)

    await db.commit()
    return {
        "updated": True,
        "log_id":  log_id,
        "macros": {
            "calories":  log.calories,
            "protein_g": log.protein_g,
            "carbs_g":   log.carbs_g,
            "fat_g":     log.fat_g,
        },
    }
