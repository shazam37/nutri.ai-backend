# app/services/image_service.py

import base64
import uuid
import logging
from datetime import datetime

import cloudinary
import cloudinary.uploader
from app.config import settings
import asyncio
from functools import partial

logger = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True,
)


async def upload_meal_image(image_base64: str, user_id: str) -> str | None:
    """
    Uploads a base64 meal image to Cloudinary.
    Returns the secure public URL, or None if upload fails.
    Images are organised under nutriai/meals/{user_id}/ with a datestamped filename.
    Never raises — a failed upload should not block meal logging.
    """
    try:
        # Strip data URI prefix if the client sends it (e.g. "data:image/jpeg;base64,...")
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]

        date_prefix = datetime.utcnow().strftime("%Y%m%d")
        public_id   = f"nutriai/meals/{user_id}/{date_prefix}_{uuid.uuid4().hex[:8]}"

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            partial(
                cloudinary.uploader.upload,
                f"data:image/jpeg;base64,{image_base64}",
                public_id=public_id,
                overwrite=False,
                resource_type="image",
                transformation=[
                    {"width": 1024, "height": 1024, "crop": "limit"},
                    {"quality": "auto:good"},
                    {"fetch_format": "auto"},
                ],
            )
        )

        url = result.get("secure_url")
        logger.info(f"[ImageService] Uploaded meal image for user {user_id}: {url}")
        return url

    except Exception as e:
        logger.error(f"[ImageService] Upload failed for user {user_id}: {e}")
        return None

async def upload_inventory_scan(image_base64: str, user_id: str) -> str | None:
    """
    Uploads a fridge/grocery scan image to Cloudinary.
    One image covers all items detected in that scan session.
    Returns secure URL or None on failure — never blocks inventory saving.
    """
    try:
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]

        date_prefix = datetime.utcnow().strftime("%Y%m%d")
        public_id   = f"nutriai/inventory/{user_id}/{date_prefix}_{uuid.uuid4().hex[:8]}"

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            partial(
                cloudinary.uploader.upload,
                f"data:image/jpeg;base64,{image_base64}",
                public_id=public_id,
                overwrite=False,
                resource_type="image",
                transformation=[
                    {"width": 1280, "height": 1280, "crop": "limit"},  # slightly larger — fridge scans have more detail
                    {"quality": "auto:good"},
                    {"fetch_format": "auto"},
                ],
            )
        )

        url = result.get("secure_url")
        logger.info(f"[ImageService] Uploaded inventory scan for user {user_id}: {url}")
        return url

    except Exception as e:
        logger.error(f"[ImageService] Inventory scan upload failed for user {user_id}: {e}")
        return None