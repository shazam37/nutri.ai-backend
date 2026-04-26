"""
Agent 1 — Daily Nutrition Coach Agent
──────────────────────────────────────
Runs automatically every morning at 8am for every user.
Checks their knowledge base, decides what kind of plan they need,
generates it, and sends a push notification — all without the user asking.

The agent has full autonomy to:
  - Decide between normal plan / binge recovery / inventory-expiry plan
  - Generate the right type of plan
  - Personalise the push notification message based on context
  - Skip silently if the user has no data yet

HOW IT INTEGRATES:
  - Called only from scheduler.py (new file)
  - Uses existing kb_service, ai_service, plan route logic
  - Does NOT modify any existing route or service
  - APNs push is stubbed for now (logs the payload) — wire real APNs later

AGENT DECISION TREE:
  read user context
    → has active plan already? → skip (don't overwrite user's accepted plan)
    → binge day detected?      → generate binge_recovery plan
    → items expiring today?    → generate inventory_expiry plan
    → normal day               → generate daily_routine plan
  → save plan
  → send push notification
"""

import logging
from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import User, MealPlan
from app.services.kb_service import get_user_context
from app.services.ai_service import generate_meal_plan
import uuid

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Push notification (stubbed — wire APNs later)
# ─────────────────────────────────────────────

async def _send_push(device_token: str | None, title: str, body: str, data: dict = {}):
    """
    Stub for APNs push notification.
    In production: use httpx to call APNs HTTP/2 endpoint with JWT auth.
    For now: logs the payload so you can verify the agent is working.
    """
    if not device_token:
        logger.info(f"[Coach Agent] No device token — push skipped. Would have sent: {title} | {body}")
        return

    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "badge": 1,
        },
        "data": data,
    }
    # TODO: replace log with real APNs HTTP/2 call
    logger.info(f"[Coach Agent] PUSH → token={device_token[:12]}... | {title} | {body}")
    logger.debug(f"[Coach Agent] Full push payload: {payload}")


# ─────────────────────────────────────────────
# Notification message builder
# ─────────────────────────────────────────────

def _build_notification(trigger: str, context: dict) -> tuple[str, str]:
    """Returns (title, body) for push notification based on agent decision."""

    name           = (context.get("user_name") or "there").split()[0]
    remaining_cal  = int(context.get("remaining_calories", 0))
    expiring       = context.get("expiring_soon", [])
    binge_days     = context.get("binge_days_count", 0)

    if trigger == "binge_recovery":
        return (
            "🔄 Reset week activated",
            f"Hey {name}, your plan has been rebalanced after {binge_days} heavy day(s). "
            f"Today's lighter target helps you stay on track."
        )
    elif trigger == "inventory_expiry":
        items_str = ", ".join(expiring[:2])
        return (
            "🥬 Use before you lose",
            f"Hey {name}, {items_str} are expiring soon! "
            f"Today's plan uses them up."
        )
    else:
        return (
            "🌅 Your plan is ready",
            f"Good morning {name}! You have {remaining_cal} kcal left today. "
            f"Tap to see today's meal plan."
        )


# ─────────────────────────────────────────────
# Core agent logic — runs for a single user
# ─────────────────────────────────────────────

async def run_for_user(db: AsyncSession, user: User):
    """
    Full agent loop for one user.
    Safe to call even if user has no data — exits cleanly.
    """
    user_id = user.id
    today   = date.today()
    logger.info(f"[Coach Agent] Running for user {user_id} ({user.name})")

    # ── Observation: load full knowledge base context ──────────────────
    context = await get_user_context(db, user_id)
    context["user_name"] = user.name  # add name for notification

    # ── Decision 1: Skip if user already has an active accepted plan ───
    existing_plan = await db.execute(
        select(MealPlan).where(
            MealPlan.user_id   == user_id,
            MealPlan.plan_date == today,
            MealPlan.is_active == True,
        )
    )
    if existing_plan.scalar_one_or_none():
        logger.info(f"[Coach Agent] User {user_id} already has active plan. Skipping.")
        return {"action": "skipped", "reason": "active_plan_exists"}

    # ── Decision 2: Choose plan type ──────────────────────────────────
    binge_mode    = context.get("binge_recovery_mode", False)
    expiring_soon = context.get("expiring_soon", [])
    meals_logged  = context.get("meals_logged_today", 0)

    if binge_mode:
        trigger = "binge_recovery"
        logger.info(f"[Coach Agent] Binge detected for {user_id}. Using recovery plan.")
    elif expiring_soon:
        trigger = "inventory_expiry"
        logger.info(f"[Coach Agent] Expiring items for {user_id}: {expiring_soon}. Using expiry plan.")
    else:
        trigger = "daily_routine"
        logger.info(f"[Coach Agent] Normal day for {user_id}. Using daily plan.")

    # ── Action: Generate meal plan ─────────────────────────────────────
    try:
        plan_data = await generate_meal_plan(context, trigger=trigger)
    except Exception as e:
        logger.error(f"[Coach Agent] Plan generation failed for {user_id}: {e}")
        return {"action": "failed", "reason": str(e)}

    # ── Action: Save plan to database ─────────────────────────────────
    new_plan = MealPlan(
        id=str(uuid.uuid4()),
        user_id=user_id,
        plan_date=today,
        plan=plan_data,
        trigger=trigger,
        is_active=False,   # user must accept — agent doesn't auto-accept
    )
    db.add(new_plan)
    await db.commit()
    await db.refresh(new_plan)
    logger.info(f"[Coach Agent] Plan saved: {new_plan.id} (trigger={trigger})")

    # ── Action: Send push notification ────────────────────────────────
    title, body = _build_notification(trigger, context)
    await _send_push(
        device_token=user.apns_device_token,
        title=title,
        body=body,
        data={
            "plan_id":    new_plan.id,
            "trigger":    trigger,
            "screen":     "meal_plan",   # tells iOS which screen to open
        }
    )

    return {
        "action":  "plan_generated",
        "user_id": user_id,
        "plan_id": new_plan.id,
        "trigger": trigger,
        "push_sent": bool(user.apns_device_token),
    }


# ─────────────────────────────────────────────
# Run for ALL users — called by scheduler
# ─────────────────────────────────────────────

async def run_for_all_users(db: AsyncSession):
    """
    Iterates all users and runs the coach agent for each.
    Called by the scheduler every morning at 8am.
    Errors for one user don't stop others.
    """
    logger.info(f"[Coach Agent] Starting morning run — {datetime.utcnow().isoformat()}")

    result = await db.execute(select(User))
    users  = result.scalars().all()

    logger.info(f"[Coach Agent] Processing {len(users)} users")

    outcomes = []
    for user in users:
        try:
            outcome = await run_for_user(db, user)
            outcomes.append(outcome)
        except Exception as e:
            logger.error(f"[Coach Agent] Unhandled error for user {user.id}: {e}")
            outcomes.append({"user_id": user.id, "action": "error", "reason": str(e)})

    success = sum(1 for o in outcomes if o.get("action") == "plan_generated")
    skipped = sum(1 for o in outcomes if o.get("action") == "skipped")
    failed  = sum(1 for o in outcomes if o.get("action") in ("failed", "error"))

    logger.info(
        f"[Coach Agent] Morning run complete — "
        f"{success} generated, {skipped} skipped, {failed} failed"
    )
    return outcomes