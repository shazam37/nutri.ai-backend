from fastapi import APIRouter, Depends, HTTPException
from app.routes.auth import get_current_user
from app.models.models import InventoryItem as InventoryItemModel
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import date, datetime
import uuid

from app.db import get_db
from app.models.models import InventoryItem

router = APIRouter(prefix="/inventory", tags=["inventory"])


class AddItemRequest(BaseModel):
    user_id: str
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
async def add_item(req: AddItemRequest, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    days_until = None
    if req.expiry_date:
        days_until = (req.expiry_date - date.today()).days

    item = InventoryItem(
        id=str(uuid.uuid4()),
        user_id=req.user_id,
        name=req.name,
        quantity=req.quantity,
        expiry_date=req.expiry_date,
        days_until_expiry=days_until,
        category=req.category,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"item_id": item.id, "name": item.name, "days_until_expiry": days_until}


@router.get("/{user_id}")
async def get_inventory(user_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
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
                "id":               i.id,
                "name":             i.name,
                "quantity":         i.quantity,
                "category":         i.category,
                "expiry_date":      str(i.expiry_date) if i.expiry_date else None,
                "days_until_expiry": (i.expiry_date - today).days if i.expiry_date else None,
                "expiring_soon":    (
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
    item_id: str, req: UpdateItemRequest, db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")

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
async def remove_item(item_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    item.is_available = False  # soft delete
    await db.commit()
    return {"removed": True}
