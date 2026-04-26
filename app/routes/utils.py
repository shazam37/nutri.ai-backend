"""
Utility Routes
──────────────
POST /utils/water              — log water intake (ml)
GET  /utils/water/{user_id}    — today's water total
POST /utils/device-token       — register APNs device token for push notifications
GET  /utils/micros/{user_id}   — today's micronutrient breakdown
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from datetime import date, datetime
import uuid

from app.db import get_db
from app.models.models import User, WaterLog
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/utils", tags=["utils"])


# ─────────────────────────────────────────────
# Water tracking
# ─────────────────────────────────────────────

class WaterLogRequest(BaseModel):
    amount_ml: float
    # Common: 250 (glass), 500 (bottle), 330 (can)

@router.post("/water")
async def log_water(
    req: WaterLogRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    log = WaterLog(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        amount_ml=req.amount_ml,
        logged_at=datetime.utcnow(),
        log_date=date.today(),
    )
    db.add(log)
    await db.commit()

    # Return updated daily total
    total = await _get_water_total(db, current_user.id, date.today())
    target_ml = 2500  # sensible default — could be user-configurable later
    return {
        "logged_ml":   req.amount_ml,
        "total_ml":    total,
        "target_ml":   target_ml,
        "remaining_ml": max(0, target_ml - total),
        "progress_pct": min(100, round((total / target_ml) * 100)),
    }


@router.get("/water/{user_id}")
async def get_water_today(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")
    total = await _get_water_total(db, user_id, date.today())
    target_ml = 2500
    return {
        "total_ml":     total,
        "target_ml":    target_ml,
        "remaining_ml": max(0, target_ml - total),
        "progress_pct": min(100, round((total / target_ml) * 100)),
    }


async def _get_water_total(db: AsyncSession, user_id: str, log_date: date) -> float:
    result = await db.execute(
        select(func.sum(WaterLog.amount_ml)).where(
            and_(WaterLog.user_id == user_id, WaterLog.log_date == log_date)
        )
    )
    return result.scalar() or 0.0


# ─────────────────────────────────────────────
# APNs device token registration
# iOS calls this right after user grants notification permission
# ─────────────────────────────────────────────

class DeviceTokenRequest(BaseModel):
    device_token: str


@router.post("/device-token")
async def register_device_token(
    req: DeviceTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.apns_device_token = req.device_token
    await db.commit()
    return {"registered": True}


# ─────────────────────────────────────────────
# Micronutrient breakdown
# Aggregates micros from today's food logs
# Groq returns micros as part of ai_response JSON
# ─────────────────────────────────────────────

@router.get("/micros/{user_id}")
async def get_micros_today(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")

    from app.models.models import FoodLog
    result = await db.execute(
        select(FoodLog).where(
            and_(FoodLog.user_id == user_id, FoodLog.log_date == date.today())
        )
    )
    logs = result.scalars().all()

    # Aggregate micros from ai_response JSON across all today's logs
    totals: dict[str, float] = {}
    for log in logs:
        micros = log.ai_response.get("micros", {})
        for nutrient, value in micros.items():
            totals[nutrient] = totals.get(nutrient, 0) + (value or 0)

    # RDI reference values for % calculation
    rdi = {
        "iron_mg":       18,
        "calcium_mg":    1000,
        "vitamin_c_mg":  90,
        "vitamin_d_iu":  600,
        "vitamin_b12_mcg": 2.4,
        "zinc_mg":       11,
        "magnesium_mg":  400,
        "potassium_mg":  3500,
        "sodium_mg":     2300,
        "omega3_g":      1.6,
        "folate_mcg":    400,
    }

    breakdown = {}
    for nutrient, rdi_val in rdi.items():
        consumed = totals.get(nutrient, 0)
        breakdown[nutrient] = {
            "consumed": round(consumed, 2),
            "rdi":      rdi_val,
            "pct":      min(100, round((consumed / rdi_val) * 100)) if rdi_val else 0,
            "status": (
                "good"     if consumed >= rdi_val * 0.8 else
                "low"      if consumed >= rdi_val * 0.4 else
                "very_low" if consumed > 0 else
                "unknown"
            ),
        }

    # Top deficits to show in iOS radar chart
    deficits = sorted(
        [{"nutrient": k, **v} for k, v in breakdown.items() if v["status"] != "good"],
        key=lambda x: x["pct"]
    )

    return {
        "breakdown":    breakdown,
        "top_deficits": deficits[:4],
        "all_good":     len(deficits) == 0,
        "logs_counted": len(logs),
    }