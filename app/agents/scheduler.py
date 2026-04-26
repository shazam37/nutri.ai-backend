"""
Scheduler
─────────
Manages all background jobs using APScheduler (AsyncIOScheduler).
Started once during app lifespan in main.py — completely non-blocking.

Jobs:
  1. coach_agent_morning_run  — every day at 8:00am IST (02:30 UTC)
  2. inventory_expiry_refresh — every day at midnight, refreshes days_until_expiry

Adding a new job: just add another scheduler.add_job() call below.
Nothing else in the codebase needs to change.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import AsyncSessionLocal
from app.agents.coach_agent import run_for_all_users

logger = logging.getLogger(__name__)

# Single scheduler instance — lives for the app lifetime
scheduler = AsyncIOScheduler(timezone="UTC")


# ─────────────────────────────────────────────
# Job: Morning coach run
# ─────────────────────────────────────────────

async def _morning_coach_job():
    """
    Wrapper that opens a DB session and runs the coach agent.
    APScheduler calls this directly — it handles its own session lifecycle.
    """
    logger.info("[Scheduler] Morning coach job triggered")
    async with AsyncSessionLocal() as db:
        try:
            outcomes = await run_for_all_users(db)
            logger.info(f"[Scheduler] Morning coach job complete: {len(outcomes)} users processed")
        except Exception as e:
            logger.error(f"[Scheduler] Morning coach job failed: {e}")


# ─────────────────────────────────────────────
# Job: Refresh inventory expiry countdowns
# ─────────────────────────────────────────────

async def _refresh_inventory_expiry():
    """
    Recalculates days_until_expiry for all inventory items every midnight.
    Without this, the value set on item creation becomes stale after 1 day.
    """
    from datetime import date
    from sqlalchemy import select, and_
    from app.models.models import InventoryItem

    logger.info("[Scheduler] Refreshing inventory expiry countdowns")
    today = date.today()

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(InventoryItem).where(
                    and_(
                        InventoryItem.is_available == True,
                        InventoryItem.expiry_date  != None,
                    )
                )
            )
            items = result.scalars().all()

            for item in items:
                item.days_until_expiry = (item.expiry_date - today).days

            await db.commit()
            logger.info(f"[Scheduler] Updated expiry for {len(items)} inventory items")
        except Exception as e:
            logger.error(f"[Scheduler] Inventory refresh failed: {e}")


# ─────────────────────────────────────────────
# Start / Stop — called from main.py lifespan
# ─────────────────────────────────────────────

def start():
    """
    Register all jobs and start the scheduler.
    Called once during app startup in main.py lifespan().
    """
    # Morning coach — 8:00am IST = 02:30 UTC
    scheduler.add_job(
        _morning_coach_job,
        trigger=CronTrigger(hour=2, minute=30, timezone="UTC"),
        id="coach_morning_run",
        name="Daily Coach Agent",
        replace_existing=True,
        misfire_grace_time=300,   # allow up to 5 min late if server was restarting
    )

    # Inventory expiry refresh — midnight UTC
    scheduler.add_job(
        _refresh_inventory_expiry,
        trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="inventory_expiry_refresh",
        name="Inventory Expiry Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info("[Scheduler] Started. Jobs registered:")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.name} | next run: {job.next_run_time}")


def stop():
    """Called on app shutdown."""
    scheduler.shutdown(wait=False)
    logger.info("[Scheduler] Stopped")