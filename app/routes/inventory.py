from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import date, timedelta
import uuid

from app.db import get_db
from app.limiter import limiter
from app.models.models import InventoryItem, User
from app.routes.auth import get_current_user
from app.services.ai_service import scan_inventory_image
from app.services.image_service import upload_inventory_scan

router = APIRouter(prefix="/inventory", tags=["inventory"])

_DEFAULT_MICROS = {
    "iron_mg": 0, "calcium_mg": 0, "vitamin_c_mg": 0,
    "vitamin_d_iu": 0, "vitamin_b12_mcg": 0, "zinc_mg": 0,
    "magnesium_mg": 0, "potassium_mg": 0, "sodium_mg": 0,
    "omega3_g": 0, "folate_mcg": 0,
}


def _normalise_micros(raw: dict | None) -> dict:
    base = dict(_DEFAULT_MICROS)
    if raw:
        for k in base:
            base[k] = float(raw.get(k, 0) or 0)
    return base


class AddItemRequest(BaseModel):
    name: str
    quantity: str | None = None
    expiry_date: date | None = None
    category: str | None = None
    image_base64: str | None = None
    # Nutrition — optional, user can supply or leave blank for manual adds
    calories:  float | None = None
    protein_g: float | None = None
    carbs_g:   float | None = None
    fat_g:     float | None = None
    fiber_g:   float | None = None
    micros:    dict  | None = None


class UpdateItemRequest(BaseModel):
    quantity:     str   | None = None
    expiry_date:  date  | None = None
    is_available: bool  | None = None
    calories:     float | None = None
    protein_g:    float | None = None
    carbs_g:      float | None = None
    fat_g:        float | None = None
    fiber_g:      float | None = None
    micros:       dict  | None = None


def _item_to_dict(i: InventoryItem, today: date) -> dict:
    """Serialise an InventoryItem to the standard response shape."""
    return {
        "id":                i.id,
        "name":              i.name,
        "quantity":          i.quantity,
        "category":          i.category,
        "expiry_date":       str(i.expiry_date) if i.expiry_date else None,
        "days_until_expiry": (i.expiry_date - today).days if i.expiry_date else None,
        "expiring_soon":     (
            (i.expiry_date - today).days <= 3 if i.expiry_date else False
        ),
        "scan_image_url":    i.scan_image_url,
        # ── nutrition ──────────────────────────────────────────────────────
        "macros": {
            "calories":  i.calories  or 0.0,
            "protein_g": i.protein_g or 0.0,
            "carbs_g":   i.carbs_g   or 0.0,
            "fat_g":     i.fat_g     or 0.0,
            "fiber_g":   i.fiber_g   or 0.0,
        },
        "micros": _normalise_micros(i.micros),
        "has_nutrition": i.calories is not None,   # lets frontend show/hide nutrition UI
    }


@router.post("/add")
async def add_item(
    req: AddItemRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    days_until = None
    if req.expiry_date:
        days_until = (req.expiry_date - date.today()).days

    image_url = None
    if req.image_base64:
        image_url = await upload_inventory_scan(req.image_base64, current_user.id)

    item = InventoryItem(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=req.name,
        scan_image_url=image_url,
        quantity=req.quantity,
        expiry_date=req.expiry_date,
        days_until_expiry=days_until,
        category=req.category,
        calories=req.calories,
        protein_g=req.protein_g,
        carbs_g=req.carbs_g,
        fat_g=req.fat_g,
        fiber_g=req.fiber_g,
        micros=_normalise_micros(req.micros) if req.micros else None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    today = date.today()
    return {
        **_item_to_dict(item, today),
        "expiring_soon": days_until is not None and days_until <= 3,
    }


@router.get("/{user_id}")
async def get_inventory(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(403, "Not authorised")

    result = await db.execute(
        select(InventoryItem).where(
            and_(InventoryItem.user_id == user_id, InventoryItem.is_available == True)
        ).order_by(InventoryItem.expiry_date.asc().nulls_last())
    )
    items = result.scalars().all()
    today = date.today()

    serialised = [_item_to_dict(i, today) for i in items]

    # Aggregate nutrition totals across all available inventory items
    # Useful for the frontend "pantry nutrition summary" dashboard panel
    total_macros = {
        "calories":  sum(i["macros"]["calories"]  for i in serialised),
        "protein_g": sum(i["macros"]["protein_g"] for i in serialised),
        "carbs_g":   sum(i["macros"]["carbs_g"]   for i in serialised),
        "fat_g":     sum(i["macros"]["fat_g"]      for i in serialised),
        "fiber_g":   sum(i["macros"]["fiber_g"]   for i in serialised),
    }

    return {
        "items":                serialised,
        "total_items":          len(items),
        "expiring_soon_count":  sum(1 for i in serialised if i["expiring_soon"]),
        "inventory_macros":     total_macros,   # ← new: pantry-level macro summary
        "items_with_nutrition": sum(1 for i in serialised if i["has_nutrition"]),
    }


@router.patch("/{item_id}")
async def update_item(
    item_id: str,
    req: UpdateItemRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if item.user_id != current_user.id:
        raise HTTPException(403, "Not authorised")

    if req.quantity     is not None: item.quantity     = req.quantity
    if req.is_available is not None: item.is_available = req.is_available
    if req.expiry_date  is not None:
        item.expiry_date        = req.expiry_date
        item.days_until_expiry  = (req.expiry_date - date.today()).days

    # Nutrition updates
    if req.calories  is not None: item.calories  = req.calories
    if req.protein_g is not None: item.protein_g = req.protein_g
    if req.carbs_g   is not None: item.carbs_g   = req.carbs_g
    if req.fat_g     is not None: item.fat_g     = req.fat_g
    if req.fiber_g   is not None: item.fiber_g   = req.fiber_g
    if req.micros    is not None: item.micros    = _normalise_micros(req.micros)

    await db.commit()
    return {"updated": True}


@router.delete("/{item_id}")
async def remove_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if item.user_id != current_user.id:
        raise HTTPException(403, "Not authorised")

    item.is_available = False   # soft delete
    await db.commit()
    return {"removed": True}


class ScanImageRequest(BaseModel):
    image_base64: str


@router.post("/scan-image")
async def scan_image_and_add(
    req: ScanImageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scan_image_url = await upload_inventory_scan(req.image_base64, current_user.id)
    scan_result    = await scan_inventory_image(req.image_base64)
    items_detected = scan_result.get("items", [])

    if not items_detected:
        return {
            "added":           [],
            "total_added":     0,
            "scan_confidence": scan_result.get("scan_confidence", 0),
            "scan_image_url":  scan_image_url,
            "message":         "No items detected. Try a clearer photo with better lighting.",
        }

    added = []
    today = date.today()

    for detected in items_detected:
        shelf_days = detected.get("estimated_shelf_days", 7)
        expiry     = today + timedelta(days=shelf_days)

        item = InventoryItem(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            name=detected["name"],
            quantity=detected.get("quantity"),
            expiry_date=expiry,
            days_until_expiry=shelf_days,
            category=detected.get("category", "other"),
            is_available=True,
            scan_image_url=scan_image_url,
            # ── nutrition from AI scan ──────────────────────────
            calories=detected.get("calories"),
            protein_g=detected.get("protein_g"),
            carbs_g=detected.get("carbs_g"),
            fat_g=detected.get("fat_g"),
            fiber_g=detected.get("fiber_g"),
            micros=detected.get("micros"),
        )
        db.add(item)
        added.append({
            **_item_to_dict(item, today),
            "ai_confidence":  detected.get("confidence", 0.7),
            "scan_image_url": scan_image_url,
        })

    await db.commit()

    return {
        "added":           added,
        "total_added":     len(added),
        "scan_confidence": scan_result.get("scan_confidence", 0),
        "scan_image_url":  scan_image_url,
        "notes":           scan_result.get("notes", ""),
        "message":         f"Added {len(added)} item(s) to your inventory.",
    }