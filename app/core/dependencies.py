"""
Shared Dependencies
────────────────────
Centralises things that multiple route files need:
  - get_current_user  (was in auth.py, imported by all other routes)
  - calculate_targets (was in users.py, imported by auth.py)

Both auth.py and users.py now import from here instead of each other.
"""

from typing import Annotated
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ─────────────────────────────────────────────
# JWT — decode + get current user
# ─────────────────────────────────────────────

def decode_token(token: str) -> dict:
    import jwt
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


def create_token(user_id: str, token_type: str) -> str:
    import jwt
    from datetime import datetime, timedelta
    expire = datetime.utcnow() + (
        timedelta(days=1) if token_type == "access"
        else timedelta(days=30)
    )
    return jwt.encode(
        {"sub": user_id, "type": token_type, "exp": expire},
        settings.JWT_SECRET,
        algorithm="HS256",
    )


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
):
    from app.models.models import User
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")
    return user


# ─────────────────────────────────────────────
# Mifflin-St Jeor calorie calculator
# ─────────────────────────────────────────────

ACTIVITY_MULTIPLIERS = {
    "sedentary":   1.2,
    "light":       1.375,
    "moderate":    1.55,
    "active":      1.725,
    "very_active": 1.9,
}

GOAL_ADJUSTMENTS = {
    "lose_weight":  -400,
    "maintain":        0,
    "gain_muscle":  +250,
}


def calculate_targets(
    age: int,
    weight_kg: float,
    height_cm: float,
    gender: str,
    activity_level: str,
    goal: str,
) -> dict:
    if gender == "male":
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
    else:
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161

    multiplier     = ACTIVITY_MULTIPLIERS.get(activity_level, 1.55)
    tdee           = bmr * multiplier
    calorie_target = tdee + GOAL_ADJUSTMENTS.get(goal, 0)
    calorie_target = round(max(1200, calorie_target))

    protein_g = round(weight_kg * 2.0)
    fat_g     = round((calorie_target * 0.25) / 9)
    carbs_g   = round((calorie_target - (protein_g * 4) - (fat_g * 9)) / 4)
    carbs_g   = max(50, carbs_g)

    return {
        "calorie_target":   float(calorie_target),
        "protein_target_g": float(protein_g),
        "carbs_target_g":   float(carbs_g),
        "fat_target_g":     float(fat_g),
        "tdee":             round(tdee),
        "bmr":              round(bmr),
    }