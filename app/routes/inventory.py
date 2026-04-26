from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import date, timedelta
import uuid

from app.db import get_db
from app.models.models import InventoryItem, User
from app.routes.auth import get_current_user
from app.services.ai_service import scan_inventory_image

router = APIRouter(prefix="/inventory", tags=["inventory"])


class AddItemRequest(BaseModel):
    name: str
    quantity: str | None = None
    expiry_date: date | None = None
    category: str | None = None
    # category: "protein" | "vegetable" | "dairy" | "grain" | "spice" | "fruit" | "other"

class UpdateItemRequest(BaseModel):
    quantity: str | None = None
    expiry_date: date | None = None
    is_available: bool | None = None


@router.post("/add")
async def add_item(
    req: AddItemRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    days_until = None
    if req.expiry_date:
        days_until = (req.expiry_date - date.today()).days

    item = InventoryItem(
        id=str(uuid.uuid4()),
        user_id=current_user.id,      # from token, not request body
        name=req.name,
        quantity=req.quantity,
        expiry_date=req.expiry_date,
        days_until_expiry=days_until,
        category=req.category,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {
        "item_id": item.id,
        "name": item.name,
        "days_until_expiry": days_until,
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
    return {
        "items": [
            {
                "id":                i.id,
                "name":              i.name,
                "quantity":          i.quantity,
                "category":          i.category,
                "expiry_date":       str(i.expiry_date) if i.expiry_date else None,
                "days_until_expiry": (i.expiry_date - today).days if i.expiry_date else None,
                "expiring_soon":     (
                    (i.expiry_date - today).days <= 3
                    if i.expiry_date else False
                ),
            }
            for i in items
        ],
        "total_items": len(items),
        "expiring_soon_count": sum(
            1 for i in items
            if i.expiry_date and (i.expiry_date - today).days <= 3
        ),
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

    if req.quantity is not None:
        item.quantity = req.quantity
    if req.expiry_date is not None:
        item.expiry_date = req.expiry_date
        item.days_until_expiry = (req.expiry_date - date.today()).days
    if req.is_available is not None:
        item.is_available = req.is_available

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
    """
    Scan a photo of your fridge or grocery bag.
    AI identifies all items and bulk-adds them to your inventory.
    Returns added items with estimated expiry dates.

    iOS flow:
      User taps "Scan fridge" → camera → capture → base64 → this endpoint
      Response shows detected items → user can confirm/edit before saving
    """
    # Step 1: AI identifies items from image
    scan_result = await scan_inventory_image(req.image_base64)
    items_detected = scan_result.get("items", [])

    if not items_detected:
        return {
            "added": [],
            "total_added": 0,
            "scan_confidence": scan_result.get("scan_confidence", 0),
            "message": "No items detected. Try a clearer photo with better lighting.",
        }

    # Step 2: Bulk-add all detected items to inventory
    added = []
    today = date.today()

    for detected in items_detected:
        shelf_days = detected.get("estimated_shelf_days", 7)
        expiry = today + timedelta(days=shelf_days)
        days_until = shelf_days

        item = InventoryItem(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            name=detected["name"],
            quantity=detected.get("quantity"),
            expiry_date=expiry,
            days_until_expiry=days_until,
            category=detected.get("category", "other"),
            is_available=True,
        )
        db.add(item)
        added.append({
            "item_id":          item.id,
            "name":             item.name,
            "quantity":         item.quantity,
            "category":         item.category,
            "expiry_date":      str(expiry),
            "days_until_expiry": days_until,
            "expiring_soon":    days_until <= 3,
            "ai_confidence":    detected.get("confidence", 0.7),
        })

    await db.commit()

    return {
        "added":            added,
        "total_added":      len(added),
        "scan_confidence":  scan_result.get("scan_confidence", 0),
        "notes":            scan_result.get("notes", ""),
        "message": f"Added {len(added)} item(s) to your inventory.",
    }