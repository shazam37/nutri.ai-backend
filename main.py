from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.db import init_db
from app.limiter import limiter
from app.routes.meal      import router as meal_router
from app.routes.inventory import router as inventory_router
from app.routes.users     import router as users_router
from app.routes.auth      import router as auth_router
from app.routes.history   import router as history_router
from app.routes.plan      import router as plan_router
from app.routes.utils     import router as utils_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="NutriAI Backend",
    version="0.2.0",
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Slow down a little."},
    )

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router,      prefix="/api/v1")
app.include_router(users_router,     prefix="/api/v1")
app.include_router(meal_router,      prefix="/api/v1")
app.include_router(inventory_router, prefix="/api/v1")
app.include_router(history_router,   prefix="/api/v1")
app.include_router(plan_router,      prefix="/api/v1")
app.include_router(utils_router,     prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}