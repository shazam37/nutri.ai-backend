"""
Knowledge Base Service
─────────────────────
Responsible for:
1. Saving a food log + updating the daily summary in one transaction
2. Building the "context window" dict that every AI call receives
3. Detecting binge days and flagging them for plan revision
4. Fetching inventory items that are expiring soon

Every AI prompt in ai_service.py calls get_user_context() first.
That context dict is what makes the AI "remember" the user.
"""

from datetime import date, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.models import User, FoodLog, DailySummary, InventoryItem, MealPlan, LogSource
import uuid


# ─────────────────────────────────────────────
# WRITE: Save a food log + upsert daily summary
# ─────────────────────────────────────────────

async def save_log(
    db: AsyncSession,
    user_id: str,
    meal_type: str,
    source: str,
    ai_result: dict,
    usda_result: dict,
    user_description: str = "",
    image_url: str | None = None,
) -> str:
    """
    Saves one FoodLog row and upserts the DailySummary for today.
    Returns the new log_id.
    """
    today = date.today()
    totals = ai_result.get("total", {})

    # 1. Create FoodLog
    log = FoodLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        log_date=today,
        meal_type=meal_type,
        source=LogSource(source),
        user_description=user_description,
        image_url=image_url,
        ai_response=ai_result,
        calories=totals.get("calories", 0),
        protein_g=totals.get("protein_g", 0),
        carbs_g=totals.get("carbs_g", 0),
        fat_g=totals.get("fat_g", 0),
        fiber_g=totals.get("fiber_g", 0),
        usda_validation=usda_result,
        ai_confidence=ai_result.get("confidence", 0.0),
    )
    db.add(log)

    # 2. Upsert DailySummary
    summary = await _get_or_create_summary(db, user_id, today)
    summary.total_calories  += log.calories
    summary.total_protein_g += log.protein_g
    summary.total_carbs_g   += log.carbs_g
    summary.total_fat_g     += log.fat_g
    summary.total_fiber_g   += log.fiber_g
    summary.meals_logged    += 1
    summary.updated_at       = datetime.utcnow()

    # 3. Recalculate remaining macros against user targets
    user = await db.get(User, user_id)
    if user:
        summary.remaining_calories  = max(0, user.calorie_target - summary.total_calories)
        summary.remaining_protein_g = max(0, user.protein_target_g - summary.total_protein_g)
        # Flag binge day: exceeded calorie target by >30%
        summary.is_binge_day = summary.total_calories > (user.calorie_target * 1.3)

    await db.commit()
    await db.refresh(log)
    return log.id


# ─────────────────────────────────────────────
# READ: Build context window for AI calls
# ─────────────────────────────────────────────

async def get_user_context(db: AsyncSession, user_id: str) -> dict:
    """
    Returns a rich context dict used by every AI prompt.
    Includes: user profile, today's totals, last 7 days history,
    inventory items, expiring items, recent binge flags.
    """
    today = date.today()
    user  = await db.get(User, user_id)

    if not user:
        return _empty_context()

    # Today's summary
    today_summary = await _get_summary(db, user_id, today)

    # Last 7 days summaries (for binge recovery logic)
    week_summaries = await _get_week_summaries(db, user_id, today)

    # Today's food logs (so AI knows exactly what was eaten)
    today_logs = await _get_today_logs(db, user_id, today)

    # Inventory items available
    inventory = await _get_available_inventory(db, user_id)

    # Items expiring in next 3 days
    expiring_soon = [
        i for i in inventory
        if i.expiry_date and (i.expiry_date - today).days <= 3
    ]

    # Was this week a binge week? (any day flagged)
    binge_days_this_week = [
        s for s in week_summaries if s.is_binge_day
    ]

    return {
        # User profile
        "user_id":              user_id,
        "calorie_target":       user.calorie_target,
        "protein_target_g":     user.protein_target_g,
        "carbs_target_g":       user.carbs_target_g,
        "fat_target_g":         user.fat_target_g,
        "dietary_restrictions": user.dietary_restrictions,

        # Today
        "today_totals": {
            "calories":   today_summary.total_calories  if today_summary else 0,
            "protein_g":  today_summary.total_protein_g if today_summary else 0,
            "carbs_g":    today_summary.total_carbs_g   if today_summary else 0,
            "fat_g":      today_summary.total_fat_g     if today_summary else 0,
        },
        "remaining_calories":  today_summary.remaining_calories  if today_summary else user.calorie_target,
        "remaining_protein_g": today_summary.remaining_protein_g if today_summary else user.protein_target_g,
        "meals_logged_today":  today_summary.meals_logged         if today_summary else 0,

        # Today's meals as readable summary for AI prompt
        "today_meals": _format_logs_for_prompt(today_logs),

        # Weekly history for binge detection
        "week_summary": _format_week_for_prompt(week_summaries, user),
        "binge_recovery_mode": len(binge_days_this_week) > 0,
        "binge_days_count":    len(binge_days_this_week),

        # Inventory
        "inventory_items":  [i.name for i in inventory],
        "expiring_soon":    [i.name for i in expiring_soon],
        "inventory_detail": [
            {
                "name": i.name,
                "quantity": i.quantity,
                "expiry_date": str(i.expiry_date) if i.expiry_date else None,
                "category": i.category,
            }
            for i in inventory
        ],
    }


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

async def _get_or_create_summary(
    db: AsyncSession, user_id: str, log_date: date
) -> DailySummary:
    summary = await _get_summary(db, user_id, log_date)
    if not summary:
        summary = DailySummary(
            id=str(uuid.uuid4()),
            user_id=user_id,
            log_date=log_date,
        )
        db.add(summary)
    return summary


async def _get_summary(
    db: AsyncSession, user_id: str, log_date: date
) -> DailySummary | None:
    result = await db.execute(
        select(DailySummary).where(
            and_(DailySummary.user_id == user_id, DailySummary.log_date == log_date)
        )
    )
    return result.scalar_one_or_none()


async def _get_week_summaries(
    db: AsyncSession, user_id: str, today: date
) -> list[DailySummary]:
    week_ago = today - timedelta(days=7)
    result = await db.execute(
        select(DailySummary).where(
            and_(
                DailySummary.user_id == user_id,
                DailySummary.log_date >= week_ago,
                DailySummary.log_date <= today,
            )
        ).order_by(DailySummary.log_date.desc())
    )
    return list(result.scalars().all())


async def _get_today_logs(
    db: AsyncSession, user_id: str, today: date
) -> list[FoodLog]:
    result = await db.execute(
        select(FoodLog).where(
            and_(FoodLog.user_id == user_id, FoodLog.log_date == today)
        ).order_by(FoodLog.logged_at)
    )
    return list(result.scalars().all())


async def _get_available_inventory(
    db: AsyncSession, user_id: str
) -> list[InventoryItem]:
    result = await db.execute(
        select(InventoryItem).where(
            and_(
                InventoryItem.user_id == user_id,
                InventoryItem.is_available == True,
            )
        )
    )
    return list(result.scalars().all())


def _format_logs_for_prompt(logs: list[FoodLog]) -> list[dict]:
    """
    Converts FoodLog rows into a compact list the AI prompt can read.
    Keeps token usage low — no raw JSON blobs.
    """
    out = []
    for log in logs:
        items = log.ai_response.get("food_items", [])
        names = ", ".join(i.get("name", "") for i in items)
        out.append({
            "meal_type": log.meal_type,
            "foods":     names,
            "calories":  log.calories,
            "protein_g": log.protein_g,
            "time":      log.logged_at.strftime("%H:%M"),
        })
    return out


def _format_week_for_prompt(
    summaries: list[DailySummary], user: User
) -> list[dict]:
    """
    7-day calorie history with over/under vs target.
    Used in binge-recovery meal plan prompt.
    """
    out = []
    for s in summaries:
        delta = s.total_calories - user.calorie_target
        out.append({
            "date":             str(s.log_date),
            "calories":         round(s.total_calories),
            "vs_target":        round(delta),   # positive = over, negative = under
            "is_binge_day":     s.is_binge_day,
            "protein_g":        round(s.total_protein_g),
        })
    return out


def _empty_context() -> dict:
    return {
        "user_id": None,
        "calorie_target": 2000,
        "protein_target_g": 150,
        "carbs_target_g": 250,
        "fat_target_g": 65,
        "dietary_restrictions": [],
        "today_totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
        "remaining_calories": 2000,
        "remaining_protein_g": 150,
        "meals_logged_today": 0,
        "today_meals": [],
        "week_summary": [],
        "binge_recovery_mode": False,
        "binge_days_count": 0,
        "inventory_items": [],
        "expiring_soon": [],
        "inventory_detail": [],
    }