"""
Rate Limiting
─────────────
Applied to AI-heavy endpoints to prevent Groq bill shock during demos.
Uses slowapi (built on limits library) with in-memory storage.

Limits:
  /meal/log         → 20 requests / minute per user
  /meal/plan        → 10 requests / minute per user
  /plan/generate    → 10 requests / minute per user
  /plan/revise-week → 5  requests / minute per user

In production, swap InMemoryStorage for RedisStorage.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

def get_user_id_or_ip(request: Request) -> str:
    """
    Rate limit key: use user_id from JWT if available, else fall back to IP.
    This means authenticated users get their own bucket, not shared with others.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            import jwt
            from app.config import settings
            token = auth.split(" ")[1]
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
            return payload.get("sub", get_remote_address(request))
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=get_user_id_or_ip)