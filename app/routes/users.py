"""
User Routes
───────────
Handles:
1. POST /users/onboard   — first-time setup (called once after signup)
2. GET  /users/{user_id} — fetch profile (for settings screen)
3. PUT  /users/{user_id} — update any profile field (settings edits)

The calorie/macro targets can either be:
  - Provided explicitly by the user ("I want 1800 kcal/day")
  - Auto-calculated from body stats using Mifflin-St Jeor + activity multiplier

iOS flow:
  App launch → check if user exists → if not → show onboarding screens
  → POST /users/onboard → store user_id locally → proceed to home
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
from typing import Literal

from app.db import get_db
from app.models.models import User
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


# ─────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────

class OnboardRequest(BaseModel):
    # Identity
    name: str

    # Body stats (used to auto-calculate calorie target)
    age: int
    weight_kg: float
    height_cm: float
    gender: Literal["male", "female", "other"]

    # Goal
    goal: Literal["lose_weight", "maintain", "gain_muscle"]
    # lose_weight  → deficit  (~300-500 kcal below TDEE)
    # maintain     → at TDEE
    # gain_muscle  → surplus  (~200-300 kcal above TDEE)

    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"]
    # sedentary    → desk job, no exercise
    # light        → 1-3 days/week exercise
    # moderate     → 3-5 days/week exercise
    # active       → 6-7 days/week exercise
    # very_active  → athlete / physical job

    dietary_restrictions: list[str] = []
    # e.g. ["vegetarian", "gluten-free", "nut-allergy", "dairy-free"]

    # Optional: override auto-calculated targets
    custom_calorie_target: float | None = None
    custom_protein_target_g: float | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    age: int | None = None
    weight_kg: float | None = None
    height_cm: float | None = None
    gender: str | None = None
    goal: str | None = None
    activity_level: str | None = None
    dietary_restrictions: list[str] | None = None
    # Directly override macro targets
    calorie_target: float | None = None
    protein_target_g: float | None = None
    carbs_target_g: float | None = None
    fat_target_g: float | None = None
    water_target_ml: float | None = None

# ─────────────────────────────────────────────
# Calorie / macro calculator
# ─────────────────────────────────────────────

ACTIVITY_MULTIPLIERS = {
    "sedentary":   1.2,
    "light":       1.375,
    "moderate":    1.55,
    "active":      1.725,
    "very_active": 1.9,
}

GOAL_ADJUSTMENTS = {
    "lose_weight":  -400,   # kcal deficit
    "maintain":        0,
    "gain_muscle":  +250,   # kcal surplus
}

def calculate_targets(
    age: int,
    weight_kg: float,
    height_cm: float,
    gender: str,
    activity_level: str,
    goal: str,
) -> dict:
    """
    Mifflin-St Jeor BMR → multiply by activity → adjust for goal.
    Then split macros:
      Protein : 2.0g per kg bodyweight (higher end, supports muscle)
      Fat     : 25% of total calories
      Carbs   : remainder
    """
    # BMR
    if gender == "male":
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
    else:
        # female and other both use this formula
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161

    # TDEE
    multiplier = ACTIVITY_MULTIPLIERS.get(activity_level, 1.55)
    tdee = bmr * multiplier

    # Goal adjustment
    calorie_target = tdee + GOAL_ADJUSTMENTS.get(goal, 0)
    calorie_target = round(max(1200, calorie_target))  # floor at 1200 kcal

    # Macro split
    protein_g = round(weight_kg * 2.0)        # 2g per kg
    fat_g     = round((calorie_target * 0.25) / 9)   # 25% of cals from fat
    # Remaining calories go to carbs
    carbs_g   = round((calorie_target - (protein_g * 4) - (fat_g * 9)) / 4)
    carbs_g   = max(50, carbs_g)  # floor at 50g carbs

    return {
        "calorie_target":   float(calorie_target),
        "protein_target_g": float(protein_g),
        "carbs_target_g":   float(carbs_g),
        "fat_target_g":     float(fat_g),
        "tdee":             round(tdee),  # useful to show user
        "bmr":              round(bmr),
    }


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.post("/onboard")
async def onboard_user(req: OnboardRequest, db: AsyncSession = Depends(get_db)):
    """
    Called once when user completes onboarding screens.
    Creates user + calculates their macro targets.
    Returns user_id — iOS should store this locally (Keychain).
    """
    # Auto-calculate targets
    calculated = calculate_targets(
        age=req.age,
        weight_kg=req.weight_kg,
        height_cm=req.height_cm,
        gender=req.gender,
        activity_level=req.activity_level,
        goal=req.goal,
    )

    # Use custom overrides if provided
    calorie_target   = req.custom_calorie_target   or calculated["calorie_target"]
    protein_target_g = req.custom_protein_target_g or calculated["protein_target_g"]

    # Recalculate carbs/fat if calorie target was overridden
    if req.custom_calorie_target:
        fat_g   = round((calorie_target * 0.25) / 9)
        carbs_g = round((calorie_target - (protein_target_g * 4) - (fat_g * 9)) / 4)
    else:
        fat_g   = calculated["fat_target_g"]
        carbs_g = calculated["carbs_target_g"]

    user = User(
        id=str(uuid.uuid4()),
        name=req.name,
        age=req.age,
        weight_kg=req.weight_kg,
        height_cm=req.height_cm,
        dietary_restrictions=req.dietary_restrictions,
        calorie_target=calorie_target,
        protein_target_g=protein_target_g,
        carbs_target_g=float(carbs_g),
        fat_target_g=float(fat_g),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return {
        "user_id": user.id,
        "name":    user.name,
        "targets": {
            "calories":  user.calorie_target,
            "protein_g": user.protein_target_g,
            "carbs_g":   user.carbs_target_g,
            "fat_g":     user.fat_target_g,
        },
        "calculated_from": {
            "bmr":  calculated["bmr"],
            "tdee": calculated["tdee"],
            "goal": req.goal,
            "activity_level": req.activity_level,
        },
        "message": f"Welcome {user.name}! Your daily target is {int(calorie_target)} kcal."
    }


@router.get("/{user_id}")
async def get_profile(user_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Fetch full user profile. Used to populate the settings screen.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")

    return {
        "user_id":    user.id,
        "name":       user.name,
        "age":        user.age,
        "weight_kg":  user.weight_kg,
        "height_cm":  user.height_cm,
        "dietary_restrictions": user.dietary_restrictions,
        "targets": {
            "calories":  user.calorie_target,
            "protein_g": user.protein_target_g,
            "carbs_g":   user.carbs_target_g,
            "fat_g":     user.fat_target_g,
        },
    }


@router.put("/{user_id}")
async def update_profile(
    user_id: str,
    req: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update any profile field. Called from the settings screen.
    If body stats change (weight, age, activity), targets are recalculated
    automatically — unless the user has explicitly set custom targets.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")

    # Track whether body stats changed (triggers recalculation)
    body_stats_changed = any([
        req.weight_kg   is not None and req.weight_kg   != user.weight_kg,
        req.height_cm   is not None and req.height_cm   != user.height_cm,
        req.age         is not None and req.age         != user.age,
    ])

    # Apply simple field updates
    if req.name                 is not None: user.name                  = req.name
    if req.age                  is not None: user.age                   = req.age
    if req.weight_kg            is not None: user.weight_kg             = req.weight_kg
    if req.height_cm            is not None: user.height_cm             = req.height_cm
    if req.gender               is not None: user.gender                = req.gender
    if req.dietary_restrictions is not None: user.dietary_restrictions  = req.dietary_restrictions

    # If explicit targets provided → use them directly (user knows best)
    if req.calorie_target   is not None: user.calorie_target   = req.calorie_target
    if req.protein_target_g is not None: user.protein_target_g = req.protein_target_g
    if req.carbs_target_g   is not None: user.carbs_target_g   = req.carbs_target_g
    if req.fat_target_g     is not None: user.fat_target_g     = req.fat_target_g

    # If body stats changed but no explicit targets → recalculate
    elif body_stats_changed and user.age and user.weight_kg and user.height_cm:
        recalculated = calculate_targets(
            age=user.age,
            weight_kg=user.weight_kg,
            height_cm=user.height_cm,
            gender=getattr(user, 'gender', 'other') or 'other',
            activity_level=getattr(user, 'activity_level', 'moderate') or 'moderate',
            goal=getattr(user, 'goal', 'maintain') or 'maintain',
        )
        user.calorie_target   = recalculated["calorie_target"]
        user.protein_target_g = recalculated["protein_target_g"]
        user.carbs_target_g   = recalculated["carbs_target_g"]
        user.fat_target_g     = recalculated["fat_target_g"]

    await db.commit()
    await db.refresh(user)

    return {
        "user_id": user.id,
        "updated": True,
        "targets": {
            "calories":  user.calorie_target,
            "protein_g": user.protein_target_g,
            "carbs_g":   user.carbs_target_g,
            "fat_g":     user.fat_target_g,
        },
    }
