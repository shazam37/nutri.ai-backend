"""
Database models for NutriAI.
Tables:
  - users            : profile + targets
  - food_logs        : every meal logged (image or text)
  - daily_summaries  : pre-aggregated daily macro totals (fast reads)
  - inventory_items  : user's fridge/pantry
  - meal_plans       : AI-generated plans, linked to a user + date
"""

import uuid
from datetime import datetime, date
from sqlalchemy import (
    String, Float, Integer, Boolean, Text,
    DateTime, Date, ForeignKey, JSON, Enum as SAEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.db import Base


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class MealType(str, enum.Enum):
    breakfast = "breakfast"
    lunch     = "lunch"
    dinner    = "dinner"
    snack     = "snack"

class LogSource(str, enum.Enum):
    image       = "image"
    text        = "text"
    quick_form  = "quick_form"


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Auth
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255))

    # Push notifications
    apns_device_token: Mapped[str | None] = mapped_column(String(500))

    # Profile
    name: Mapped[str | None]            = mapped_column(String(120))
    age: Mapped[int | None]             = mapped_column(Integer)
    weight_kg: Mapped[float | None]     = mapped_column(Float)
    height_cm: Mapped[float | None]     = mapped_column(Float)
    gender: Mapped[str | None]          = mapped_column(String(20))
    # "male" | "female" | "other"

    goal: Mapped[str | None]            = mapped_column(String(30))
    # "lose_weight" | "maintain" | "gain_muscle"

    activity_level: Mapped[str | None]  = mapped_column(String(30))
    # "sedentary" | "light" | "moderate" | "active" | "very_active"

    dietary_restrictions: Mapped[list]  = mapped_column(JSON, default=list)
    # e.g. ["vegetarian", "gluten-free", "nut-allergy"]

    # Daily targets (set during onboarding or auto-calculated)
    calorie_target: Mapped[float]   = mapped_column(Float, default=2000.0)
    protein_target_g: Mapped[float] = mapped_column(Float, default=150.0)
    carbs_target_g: Mapped[float]   = mapped_column(Float, default=250.0)
    fat_target_g: Mapped[float]     = mapped_column(Float, default=65.0)

    # Relationships
    food_logs:       Mapped[list["FoodLog"]]       = relationship(back_populates="user")
    daily_summaries: Mapped[list["DailySummary"]]  = relationship(back_populates="user")
    inventory_items: Mapped[list["InventoryItem"]] = relationship(back_populates="user")
    meal_plans:      Mapped[list["MealPlan"]]      = relationship(back_populates="user")


# ─────────────────────────────────────────────
# Food Logs  (one row per meal logged)
# ─────────────────────────────────────────────

class FoodLog(Base):
    __tablename__ = "food_logs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str]  = mapped_column(ForeignKey("users.id"), index=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    log_date: Mapped[date]      = mapped_column(Date, index=True)  # for fast daily queries

    meal_type: Mapped[MealType] = mapped_column(SAEnum(MealType))
    source:    Mapped[LogSource] = mapped_column(SAEnum(LogSource))

    # Raw inputs
    user_description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None]        = mapped_column(String(500))
    # (store image in S3/R2, save URL here — don't store base64 in DB)

    # AI output — full structured response stored as JSON
    ai_response: Mapped[dict] = mapped_column(JSON)
    # Shape: { food_items: [...], total: {...}, confidence: 0.85, notes: "" }

    # Flattened totals for fast aggregation (denormalised from ai_response)
    calories:   Mapped[float] = mapped_column(Float, default=0)
    protein_g:  Mapped[float] = mapped_column(Float, default=0)
    carbs_g:    Mapped[float] = mapped_column(Float, default=0)
    fat_g:      Mapped[float] = mapped_column(Float, default=0)
    fiber_g:    Mapped[float] = mapped_column(Float, default=0)

    # USDA validation result
    usda_validation: Mapped[dict | None] = mapped_column(JSON)
    # Shape: { matched: bool, usda_name: str, accuracy_delta: 0.08 }

    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    user: Mapped["User"] = relationship(back_populates="food_logs")


# ─────────────────────────────────────────────
# Daily Summary  (pre-aggregated per user per day)
# Updated every time a FoodLog is saved.
# iOS reads this for the macro rings — fast single-row query.
# ─────────────────────────────────────────────

class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id:  Mapped[str]  = mapped_column(ForeignKey("users.id"), index=True)
    log_date: Mapped[date] = mapped_column(Date, index=True)

    # Totals
    total_calories:  Mapped[float] = mapped_column(Float, default=0)
    total_protein_g: Mapped[float] = mapped_column(Float, default=0)
    total_carbs_g:   Mapped[float] = mapped_column(Float, default=0)
    total_fat_g:     Mapped[float] = mapped_column(Float, default=0)
    total_fiber_g:   Mapped[float] = mapped_column(Float, default=0)
    meals_logged:    Mapped[int]   = mapped_column(Integer, default=0)

    # Derived fields (calculated on write)
    remaining_calories:  Mapped[float] = mapped_column(Float, default=0)
    remaining_protein_g: Mapped[float] = mapped_column(Float, default=0)

    # Flags
    is_binge_day: Mapped[bool] = mapped_column(Boolean, default=False)
    # True if calories > 130% of target — triggers plan revision

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship(back_populates="daily_summaries")


# ─────────────────────────────────────────────
# Inventory Items
# ─────────────────────────────────────────────

class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str]    = mapped_column(ForeignKey("users.id"), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    name: Mapped[str]           = mapped_column(String(200))
    quantity: Mapped[str | None] = mapped_column(String(100))
    # e.g. "500g", "1 pack", "6 eggs"

    expiry_date: Mapped[date | None] = mapped_column(Date)
    days_until_expiry: Mapped[int | None] = mapped_column(Integer)
    # Computed column refreshed daily by a background job

    category: Mapped[str | None] = mapped_column(String(50))
    # e.g. "protein", "vegetable", "dairy", "grain", "spice"

    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set to False when user marks as used/finished

    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="inventory_items")


# ─────────────────────────────────────────────
# Meal Plans  (AI-generated, stored per user per day)
# ─────────────────────────────────────────────

class MealPlan(Base):
    __tablename__ = "meal_plans"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id:   Mapped[str]  = mapped_column(ForeignKey("users.id"), index=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Full AI-generated plan as JSON
    plan: Mapped[dict] = mapped_column(JSON)
    # Shape: { meals: [{ meal_type, name, ingredients[], macros{}, recipe_steps[] }] }

    # Why this plan was generated
    trigger: Mapped[str | None] = mapped_column(String(50))
    # "daily_routine" | "binge_recovery" | "inventory_expiry" | "user_request"

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(back_populates="meal_plans")

class WaterLog(Base):
    __tablename__ = "water_logs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id:   Mapped[str]      = mapped_column(ForeignKey("users.id"), index=True)
    amount_ml: Mapped[float]    = mapped_column(Float)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    log_date:  Mapped[date]     = mapped_column(Date, index=True)