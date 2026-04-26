# NutriAI — Backend API

> AI-powered fitness and diet assistant backend. Built with FastAPI, PostgreSQL, and Groq.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Agents](#agents)
- [Testing](#testing)
- [Deployment](#deployment)
- [Roadmap](#roadmap)

---

## Overview

NutriAI backend powers an iOS fitness and diet assistant. Core capabilities:

- **AI calorie estimation** — analyse food from photos or text descriptions using Groq vision models
- **Adaptive meal planning** — context-aware plans that account for daily history, inventory, and binge recovery
- **Inventory tracking** — manage your fridge with expiry alerts and image scanning
- **Micronutrient tracking** — daily breakdown of 11 key nutrients with deficit detection
- **Agentic AI** — proactive morning coach that generates plans without being asked; multi-step food analyser that self-corrects low-confidence estimates

---

## Architecture

```
iOS App
   │
   ▼
FastAPI (Python)
   ├── routes/          ← HTTP endpoints
   ├── services/        ← AI (Groq), USDA validation, knowledge base
   ├── agents/          ← Agentic AI loops + APScheduler
   └── models/          ← SQLAlchemy ORM models
   │
   ▼
PostgreSQL            ← persistent storage
   │
Groq API              ← LLM inference (Llama 4 Scout vision + Llama 3.3 70B)
USDA FoodData API     ← nutrition validation
```

**Request flow for food logging:**
```
POST /meal/log
  → analyser_agent.analyze_food_agentic()   [Agent 2 — confidence loop]
  → groq: llama-4-scout (vision/text)
  → usda_service.validate_food()            [cross-reference]
  → kb_service.save_log()                   [write + upsert daily summary]
  → return unified response to iOS
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115 |
| Language | Python 3.12 |
| Database | PostgreSQL 16 (SQLAlchemy async) |
| AI Inference | Groq API |
| Vision Model | `meta-llama/llama-4-scout-17b-16e-instruct` |
| Text Model | `llama-3.3-70b-versatile` |
| Nutrition Validation | USDA FoodData Central API |
| Auth | JWT (PyJWT + bcrypt) |
| Scheduling | APScheduler 3.10 |
| Rate Limiting | SlowAPI |
| Testing | pytest + httpx |

---

## Project Structure

```
nutriai-backend/
├── app/
│   ├── main.py                  # FastAPI app, middleware, router registration
│   ├── config.py                # Pydantic settings (reads from .env)
│   ├── db.py                    # Async SQLAlchemy engine + session
│   ├── limiter.py               # SlowAPI rate limiter config
│   │
│   ├── models/
│   │   └── models.py            # User, FoodLog, DailySummary, InventoryItem,
│   │                            #   MealPlan, WaterLog
│   │
│   ├── routes/
│   │   ├── auth.py              # POST /signup /login /refresh, GET /me
│   │   ├── users.py             # GET/PUT /users/{id}, POST /onboard
│   │   ├── meal.py              # POST /meal/log /plan /suggest-from-inventory
│   │   ├── inventory.py         # CRUD /inventory, POST /scan-image
│   │   ├── history.py           # GET daily/logs, PATCH/DELETE log
│   │   ├── plan.py              # POST /generate /accept /revise-week, GET /active
│   │   ├── utils.py             # Water, device token, micros
│   │   └── agents.py            # Manual agent triggers, scheduler status
│   │
│   ├── services/
│   │   ├── ai_service.py        # Groq calls: analyze_food, generate_meal_plan,
│   │   │                        #   suggest_from_inventory, scan_inventory_image
│   │   ├── kb_service.py        # Knowledge base: save_log, get_user_context
│   │   └── usda_service.py      # USDA FoodData Central API wrapper
│   │
│   └── agents/
│       ├── analyser_agent.py    # Agent 2: multi-step food analyser
│       ├── coach_agent.py       # Agent 1: daily nutrition coach
│       └── scheduler.py         # APScheduler: 8am coach run + midnight expiry refresh
│
├── tests/
│   ├── conftest.py              # Shared fixtures, State object
│   ├── test_01_auth.py          # 10 auth tests
│   ├── test_02_users.py         # 7 user profile tests
│   ├── test_03_meal_logging.py  # 9 meal logging tests
│   ├── test_04_inventory.py     # 10 inventory tests
│   ├── test_05_history.py       # 9 history tests
│   ├── test_06_meal_plans.py    # 8 meal plan tests
│   └── test_07_utils.py         # 12 utils + agent tests
│
├── docker-compose.yml           # Local Postgres
├── pytest.ini                   # Test configuration
├── run_tests.py                 # Test runner with shortcuts
├── Procfile                     # Web process definition
├── requirements.txt
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- Docker (for local Postgres)
- Groq API key — [console.groq.com](https://console.groq.com)
- USDA API key — [fdc.nal.usda.gov/api-key-signup](https://fdc.nal.usda.gov/api-key-signup) (free)

### Local setup

```bash
# 1. Clone the repo
git clone https://github.com/your-org/nutriai-backend.git
cd nutriai-backend

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env
# Edit .env — fill in GROQ_API_KEY, USDA_API_KEY, JWT_SECRET

# 5. Start Postgres
docker-compose up -d

# 6. Run the server
uvicorn app.main:app --reload
```

Server starts at `http://localhost:8000`
Interactive API docs at `http://localhost:8000/docs`

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | ✅ | Groq API key for LLM inference |
| `USDA_API_KEY` | ✅ | USDA FoodData Central API key (free) |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `JWT_SECRET` | ✅ | Secret for signing JWT tokens (min 32 chars) |

Generate a secure JWT secret:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

`.env.example`:
```
GROQ_API_KEY=gsk_...
USDA_API_KEY=...
DATABASE_URL=postgresql+asyncpg://nutriai:nutriai@localhost:5432/nutriai
JWT_SECRET=your-long-random-secret-here
```

---

## API Reference

Base URL: `https://your-app.railway.app/api/v1`
Full interactive docs: `https://your-app.railway.app/docs`

All protected endpoints require:
```
Authorization: Bearer <access_token>
```

### Auth

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/signup` | ❌ | Create account + onboarding in one call |
| `POST` | `/auth/login` | ❌ | Get access + refresh tokens |
| `POST` | `/auth/refresh` | ❌ | Exchange refresh token for new access token |
| `GET` | `/auth/me` | ✅ | Get current user profile (iOS uses on launch) |

**Signup request:**
```json
{
  "email": "user@example.com",
  "password": "securepass",
  "name": "John",
  "age": 25,
  "weight_kg": 70,
  "height_cm": 175,
  "gender": "male",
  "goal": "lose_weight",
  "activity_level": "moderate",
  "dietary_restrictions": []
}
```

**Signup response:**
```json
{
  "user_id": "uuid",
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "targets": {
    "calories": 2194.0,
    "protein_g": 140.0,
    "carbs_g": 271.0,
    "fat_g": 61.0
  }
}
```

Token expiry: access = 1 day, refresh = 30 days.

---

### Meal Logging

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/meal/log` | Log a meal (image or text) |
| `POST` | `/meal/plan` | Get AI meal suggestions for remaining meals |
| `POST` | `/meal/suggest-from-inventory` | Suggest meals from current inventory |
| `GET` | `/meal/context/{user_id}` | Full knowledge base context (debug) |

**Log a meal:**
```json
POST /meal/log
{
  "description": "one medium banana",
  "meal_type": "snack"
}
```

**Response:**
```json
{
  "log_id": "uuid",
  "food_items": [
    {
      "name": "Banana",
      "quantity": "1 medium",
      "calories": 105.0,
      "protein_g": 1.3,
      "carbs_g": 26.9,
      "fat_g": 0.3,
      "fiber_g": 3.1
    }
  ],
  "total_macros": { "calories": 105, "protein_g": 1.3, "carbs_g": 26.9, "fat_g": 0.3 },
  "ai_confidence": 0.9,
  "usda_validation": { "matched": true, "accuracy_delta": 0.08, "flag": "accurate" },
  "daily_totals": { "calories": 105, "protein_g": 1.3 },
  "remaining_calories": 2089.0,
  "meals_logged_today": 1,
  "binge_alert": false
}
```

`meal_type` options: `breakfast` | `lunch` | `dinner` | `snack`

---

### Meal Plans

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/plan/generate` | Generate + optionally save a plan |
| `POST` | `/plan/accept/{plan_id}` | Accept a suggested plan |
| `GET` | `/plan/active/{user_id}` | Get today's active plan |
| `POST` | `/plan/revise-week` | Revise rest of week after binge |

---

### Inventory

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/inventory/add` | Add item manually |
| `POST` | `/inventory/scan-image` | Scan photo → bulk add detected items |
| `GET` | `/inventory/{user_id}` | Get all available items (sorted by expiry) |
| `PATCH` | `/inventory/{item_id}` | Update quantity/expiry |
| `DELETE` | `/inventory/{item_id}` | Soft-delete item |

---

### History

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/history/{user_id}/daily?days=7` | Daily calorie chart data + streak |
| `GET` | `/history/{user_id}/logs?date=YYYY-MM-DD` | All logs for a specific date |
| `PATCH` | `/history/log/{log_id}` | Edit a food log (corrects daily summary) |
| `DELETE` | `/history/log/{log_id}` | Delete a food log (reverts daily summary) |

---

### Utils

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/utils/water` | Log water intake (ml) |
| `GET` | `/utils/water/{user_id}` | Today's water total + progress |
| `POST` | `/utils/device-token` | Register APNs device token |
| `GET` | `/utils/micros/{user_id}` | Micronutrient breakdown (11 nutrients) |

---

### Agents (Dev/Admin)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/agents/trigger-coach` | Manually run coach agent for current user |
| `POST` | `/agents/trigger-coach-all` | Run coach for all users |
| `GET` | `/agents/scheduler-status` | View scheduled jobs + next run times |

---

## Agents

Two agentic AI systems run alongside the standard request-response API.

### Agent 1 — Daily Nutrition Coach
Runs automatically every morning at 8am IST via APScheduler. For each user it:
1. Reads full knowledge base context (history, inventory, binge flags)
2. Decides plan type: `daily_routine` | `binge_recovery` | `inventory_expiry`
3. Generates and saves a personalised meal plan
4. Sends a push notification (APNs — stubbed in v1, wire with real certs in v2)

Trigger manually during development:
```bash
POST /api/v1/agents/trigger-coach
```

### Agent 2 — Multi-step Food Analyser
Wraps every `/meal/log` call. If AI confidence < 0.75:
1. Searches USDA for the primary food item
2. Re-prompts Groq with USDA calibration data
3. Reconciles both estimates and returns the best result

High confidence results return in 1 step — identical performance to a direct call.

Response includes audit trail:
```json
{
  "agent_invoked": true,
  "agent_steps": [
    { "step": 1, "action": "initial_analysis", "confidence": 0.52 },
    { "step": 2, "action": "usda_lookup", "matched": true },
    { "step": 3, "action": "usda_calibrated_reanalysis", "confidence_after": 0.81 }
  ],
  "usda_calibrated": true
}
```

---

## Testing

```bash
# Install test dependencies
pip install pytest httpx

# Run all 65 tests
pytest tests/ -v

# Run specific module
pytest tests/test_01_auth.py -v

# Via shortcut runner
python run_tests.py               # all
python run_tests.py auth          # auth only
python run_tests.py meals         # meal logging only
python run_tests.py inventory
python run_tests.py history
python run_tests.py plans
python run_tests.py utils

# Against a deployed server
python run_tests.py --url https://your-app.railway.app
```

Tests are stateful — they run in order and share a single test user created at the start of each run. Each run creates a fresh user (unique email) so re-runs never conflict.

---

## Roadmap

### V1 (current — POC)
- [x] JWT authentication
- [x] Food logging — image + text
- [x] AI macro estimation (Groq)
- [x] USDA nutrition validation
- [x] Daily knowledge base
- [x] Inventory tracking + expiry alerts
- [x] Image-based inventory scanning
- [x] Meal plan generation
- [x] Binge detection + weekly plan revision
- [x] Micronutrient tracking
- [x] Water logging
- [x] Agentic food analyser (confidence loop)
- [x] Daily coach agent (scheduled)
- [x] Rate limiting
- [x] 65 automated integration tests

### V2
- [ ] HealthKit / Apple Watch integration
- [ ] APNs push notifications (real certs)
- [ ] S3/R2 image upload (replace base64)
- [ ] MCP grocery delivery integration (Blinkit/Swiggy)
- [ ] On-device CoreML food classifier
- [ ] Weekly review agent (Sunday night report)
- [ ] Alembic database migrations
- [ ] Redis caching for USDA responses

---

## Contributing

1. Branch from `main`
2. Follow existing route/service/model patterns
3. Add tests to the relevant `tests/test_XX_*.py` module
4. Run `pytest tests/ -v` — all 65 must pass
5. Open a PR

---

## License

MIT
