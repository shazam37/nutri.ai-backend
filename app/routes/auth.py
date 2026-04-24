"""
Auth Routes
───────────
POST /auth/signup  — create account + run onboarding in one call
POST /auth/login   — returns access + refresh JWT tokens
POST /auth/refresh — get a new access token using refresh token
GET  /auth/me      — returns current user from token (iOS uses on app launch)

JWT Strategy:
  access_token  — short lived (1 day), sent with every request
  refresh_token — long lived (30 days), used only to get new access token
  iOS stores both in Keychain, never in UserDefaults
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import bcrypt
import jwt

from app.db import get_db
from app.config import settings
from app.models.models import User
from app.routes.users import calculate_targets

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ─────────────────────────────────────────────
# Token helpers
# ─────────────────────────────────────────────

def create_token(user_id: str, token_type: str) -> str:
    expire = datetime.utcnow() + (
        timedelta(days=1) if token_type == "access"
        else timedelta(days=30)
    )
    return jwt.encode(
        {"sub": user_id, "type": token_type, "exp": expire},
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")
    return user


# ─────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    age: int
    weight_kg: float
    height_cm: float
    gender: Literal["male", "female", "other"]
    goal: Literal["lose_weight", "maintain", "gain_muscle"]
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"]
    dietary_restrictions: list[str] = []
    custom_calorie_target: float | None = None
    custom_protein_target_g: float | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.post("/signup", status_code=201)
async def signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()

    calculated = calculate_targets(
        age=req.age, weight_kg=req.weight_kg, height_cm=req.height_cm,
        gender=req.gender, activity_level=req.activity_level, goal=req.goal,
    )
    calorie_target   = req.custom_calorie_target   or calculated["calorie_target"]
    protein_target_g = req.custom_protein_target_g or calculated["protein_target_g"]
    fat_g   = round((calorie_target * 0.25) / 9)
    carbs_g = round((calorie_target - (protein_target_g * 4) - (fat_g * 9)) / 4)

    user = User(
        id=str(uuid.uuid4()),
        email=req.email,
        hashed_password=hashed,
        name=req.name,
        age=req.age,
        weight_kg=req.weight_kg,
        height_cm=req.height_cm,
        gender=req.gender,
        goal=req.goal,
        activity_level=req.activity_level,
        dietary_restrictions=req.dietary_restrictions,
        calorie_target=calorie_target,
        protein_target_g=float(protein_target_g),
        carbs_target_g=float(max(50, carbs_g)),
        fat_target_g=float(fat_g),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return {
        "user_id":       user.id,
        "access_token":  create_token(user.id, "access"),
        "refresh_token": create_token(user.id, "refresh"),
        "token_type":    "bearer",
        "targets": {
            "calories":  user.calorie_target,
            "protein_g": user.protein_target_g,
            "carbs_g":   user.carbs_target_g,
            "fat_g":     user.fat_target_g,
        },
    }


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not bcrypt.checkpw(req.password.encode(), user.hashed_password.encode()):
        raise HTTPException(401, "Invalid email or password")

    return {
        "user_id":       user.id,
        "access_token":  create_token(user.id, "access"),
        "refresh_token": create_token(user.id, "refresh"),
        "token_type":    "bearer",
    }


@router.post("/refresh")
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid token type")
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")
    return {
        "access_token": create_token(user.id, "access"),
        "token_type":   "bearer",
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """
    iOS calls this on every app launch to verify token + fetch latest profile.
    401 → show login screen. 200 → go to home.
    """
    return {
        "user_id":  current_user.id,
        "name":     current_user.name,
        "email":    current_user.email,
        "targets": {
            "calories":  current_user.calorie_target,
            "protein_g": current_user.protein_target_g,
            "carbs_g":   current_user.carbs_target_g,
            "fat_g":     current_user.fat_target_g,
        },
        "dietary_restrictions": current_user.dietary_restrictions,
        "goal":           current_user.goal,
        "activity_level": current_user.activity_level,
    }