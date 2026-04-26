"""
Agent Routes — for testing and manual triggers
───────────────────────────────────────────────
POST /agents/trigger-coach         — manually run coach agent for current user
POST /agents/trigger-coach-all     — run coach for all users (admin only in prod)
GET  /agents/scheduler-status      — see scheduled jobs and next run times

These endpoints let you test both agents without waiting for the scheduler.
In production, remove or auth-gate /trigger-coach-all.
"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models.models import User
from app.agents.coach_agent import run_for_user, run_for_all_users
from app.agents.scheduler import scheduler
from app.routes.auth import get_current_user

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)


@router.post("/trigger-coach")
async def trigger_coach_for_me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger the coach agent for the current user.
    Use this to test the agent immediately without waiting for 8am.
    Returns the full agent outcome including what plan was generated and why.
    """
    logger.info(f"[Agent Route] Manual coach trigger for {current_user.id}")
    outcome = await run_for_user(db, current_user)
    return {
        "triggered_for": current_user.id,
        "outcome": outcome,
    }


@router.post("/trigger-coach-all")
async def trigger_coach_all_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # In production: add an is_admin check here
):
    """
    Manually trigger the coach agent for ALL users.
    Same as what the scheduler runs at 8am.
    Useful for testing the full fleet behaviour.
    """
    logger.info(f"[Agent Route] Manual all-user coach trigger by {current_user.id}")
    outcomes = await run_for_all_users(db)
    return {
        "triggered_by": current_user.id,
        "total_users":  len(outcomes),
        "outcomes":     outcomes,
    }


@router.get("/scheduler-status")
async def get_scheduler_status(
    current_user: User = Depends(get_current_user),
):
    """
    Returns all registered scheduled jobs and their next run times.
    Use this to confirm the scheduler is running correctly.
    """
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id":            job.id,
            "name":          job.name,
            "next_run_time": str(job.next_run_time),
            "trigger":       str(job.trigger),
        })

    return {
        "scheduler_running": scheduler.running,
        "jobs":              jobs,
        "total_jobs":        len(jobs),
    }