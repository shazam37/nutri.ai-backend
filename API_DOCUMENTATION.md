# NutriAI Backend API Documentation

**Base URL:** `/api/v1`  
**Version:** 0.2.0  
**Auth:** Bearer token (JWT) in `Authorization` header  
**Rate Limiting:** Applied to certain endpoints (see individual endpoints)

---

## Table of Contents
1. [Authentication](#authentication)
2. [User Management](#user-management)
3. [Meal Logging](#meal-logging)
4. [Meal Plans](#meal-plans)
5. [Inventory Management](#inventory-management)
6. [History & Analytics](#history--analytics)
7. [Utilities](#utilities)
8. [Error Handling](#error-handling)

---

## Authentication

### POST /auth/signup — Create Account
Creates a new user account with complete profile setup in one call.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securePassword123",
  "name": "John Doe",
  "age": 30,
  "weight_kg": 75.0,
  "height_cm": 180.0,
  "gender": "male",  // "male" | "female" | "other"
  "goal": "lose_weight",  // "lose_weight" | "maintain" | "gain_muscle"
  "activity_level": "moderate",  // "sedentary" | "light" | "moderate" | "active" | "very_active"
  "dietary_restrictions": ["vegetarian", "gluten-free"],  // optional, array of strings
  "custom_calorie_target": null,  // optional, override auto-calculated value
  "custom_protein_target_g": null  // optional, override auto-calculated value
}
```

**Response:** `201 Created`
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "targets": {
    "calories": 2200,
    "protein_g": 150,
    "carbs_g": 245,
    "fat_g": 65
  }
}
```

**Notes:**
- Targets are **auto-calculated** using Mifflin-St Jeor formula + activity multiplier + goal adjustment
- If `custom_*_target` fields provided, they override calculated values
- **Macro split:** Protein 2g/kg body weight, Fat 25% of calories, Carbs remainder (min 50g)

---

### POST /auth/login — User Login
Authenticate with email and password.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securePassword123"
}
```

**Response:** `200 OK`
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

---

### POST /auth/refresh — Refresh Access Token
Use refresh token to get a new access token.

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Token Strategy:**
- `access_token`: Short-lived (1 day) — include in every request header
- `refresh_token`: Long-lived (30 days) — store securely in Keychain, use only to refresh
- **iOS storage:** Both in Keychain, never in UserDefaults

---

### GET /auth/me — Get Current User Profile
Verify token validity and fetch current user. **Call on every app launch.**

**Request Headers:**
```
Authorization: Bearer {access_token}
```

**Response:** `200 OK`
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "John Doe",
  "email": "user@example.com",
  "targets": {
    "calories": 2200,
    "protein_g": 150,
    "carbs_g": 245,
    "fat_g": 65
  },
  "dietary_restrictions": ["vegetarian", "gluten-free"],
  "goal": "lose_weight",
  "activity_level": "moderate"
}
```

**Error Handling on iOS:**
- `401 Unauthorized` → Token expired, try refresh. If refresh fails → show login screen
- `200` → Proceed to home screen

---

## User Management

### POST /users/onboard — Complete Onboarding
Called once after signup to collect detailed profile (alternative to signup if separate flow).

**Request:**
```json
{
  "name": "John Doe",
  "age": 30,
  "weight_kg": 75.0,
  "height_cm": 180.0,
  "gender": "male",
  "goal": "lose_weight",
  "activity_level": "moderate",
  "dietary_restrictions": ["vegetarian"],
  "custom_calorie_target": null,
  "custom_protein_target_g": null
}
```

**Response:** `200 OK`
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "John Doe",
  "targets": {
    "calories": 2200,
    "protein_g": 150,
    "carbs_g": 245,
    "fat_g": 65
  },
  "calculated_from": {
    "bmr": 1680,
    "tdee": 2601,
    "goal": "lose_weight",
    "activity_level": "moderate"
  },
  "message": "Welcome John Doe! Your daily target is 2200 kcal."
}
```

---

### GET /users/{user_id} — Get User Profile
Fetch full user profile (for settings screen).

**Request Headers:**
```
Authorization: Bearer {access_token}
```

**Response:** `200 OK`
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "John Doe",
  "age": 30,
  "weight_kg": 75.0,
  "height_cm": 180.0,
  "dietary_restrictions": ["vegetarian"],
  "targets": {
    "calories": 2200,
    "protein_g": 150,
    "carbs_g": 245,
    "fat_g": 65
  }
}
```

---

### PUT /users/{user_id} — Update User Profile
Update any profile field. Body stats changes trigger auto-recalculation of targets (unless custom targets set).

**Request:**
```json
{
  "name": "John Updated",
  "weight_kg": 73.0,
  "age": 31,
  "height_cm": 182.0,
  "gender": "male",
  "goal": "maintain",
  "activity_level": "active",
  "dietary_restrictions": ["vegan"],
  "calorie_target": null,      // optional override
  "protein_target_g": null,    // optional override
  "carbs_target_g": null,      // optional override
  "fat_target_g": null         // optional override
}
```

**Response:** `200 OK`
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "updated": true,
  "targets": {
    "calories": 2200,
    "protein_g": 146,
    "carbs_g": 245,
    "fat_g": 61
  }
}
```

**Auto-Recalculation Logic:**
- If body stats (weight/height/age) change but no explicit targets provided → targets recalculated
- If explicit targets provided → they override, no recalculation
- Useful for: Settings screen adjustments

---

## Meal Logging

### POST /meal/log — Log a Meal
Main meal logging endpoint. Accepts image (base64) and/or text description. Returns AI-analyzed macros + USDA validation.

**Rate Limit:** 20/minute

**Request:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "image_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAA...",  // optional
  "description": "Grilled chicken with rice and broccoli",          // optional
  "meal_type": "lunch",                                              // breakfast | lunch | dinner | snack
  "image_url": "https://s3.amazonaws.com/bucket/image.jpg"          // optional, S3 URL after upload
}
```

**Note:** Must provide at least `image_base64` or `description`.

**Response:** `200 OK`
```json
{
  "log_id": "660e8400-e29b-41d4-a716-446655441111",
  "food_items": [
    {
      "name": "Grilled Chicken Breast",
      "quantity": "150g",
      "calories": 165,
      "protein_g": 31,
      "carbs_g": 0,
      "fat_g": 3.6
    },
    {
      "name": "White Rice",
      "quantity": "150g",
      "calories": 195,
      "protein_g": 4.3,
      "carbs_g": 43,
      "fat_g": 0.3
    },
    {
      "name": "Broccoli",
      "quantity": "100g",
      "calories": 34,
      "protein_g": 2.8,
      "carbs_g": 7,
      "fat_g": 0.4
    }
  ],
  "total_macros": {
    "calories": 394,
    "protein_g": 38.1,
    "carbs_g": 50,
    "fat_g": 4.3,
    "fiber_g": 2.1
  },
  "ai_confidence": 0.92,
  "ai_notes": "High-confidence identification: grilled chicken, rice, and broccoli. Portions estimated from image scale.",
  "usda_validation": {
    "matched": true,
    "database_entry": "Chicken, broilers or fryers, breast, meat only, cooked, grilled",
    "usda_confidence": 0.88
  },
  "daily_totals": {
    "calories": 1250,
    "protein_g": 87,
    "carbs_g": 145,
    "fat_g": 32
  },
  "remaining_calories": 950,
  "remaining_protein_g": 63,
  "remaining_meals_today": 2,
  "binge_alert": false
}
```

**Response Fields:**
- `log_id`: Use to edit/delete this log later
- `ai_confidence`: 0–1, higher = more reliable
- `usda_validation`: USDA database match (used for fact-checking AI)
- `daily_totals`: User's macro totals for today (including this log)
- `binge_alert`: `true` if daily total > 30% above target (triggers recovery mode)

**Error Responses:**
- `400 Bad Request`: No image or description provided
- `502 Bad Gateway`: AI analysis failed

---

### POST /meal/plan — Generate Meal Plan
Generate AI meal plan for remaining meals today. Automatically switches to binge-recovery mode if binge detected.

**Rate Limit:** 10/minute

**Request:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "trigger": "user_request"  // "daily_routine" | "binge_recovery" | "inventory_expiry" | "user_request"
}
```

**Response:** `200 OK`
```json
{
  "meals": [
    {
      "meal_type": "lunch",
      "suggested_foods": [
        {
          "name": "Grilled Salmon",
          "quantity": "150g",
          "target_calories": 280,
          "protein_g": 35,
          "carbs_g": 0,
          "fat_g": 18
        },
        {
          "name": "Sweet Potato",
          "quantity": "150g",
          "target_calories": 103,
          "protein_g": 1.6,
          "carbs_g": 23.4,
          "fat_g": 0.1
        }
      ],
      "total_macros": {
        "calories": 383,
        "protein_g": 36.6,
        "carbs_g": 23.4,
        "fat_g": 18.1
      }
    },
    {
      "meal_type": "snack",
      "suggested_foods": [
        {
          "name": "Greek Yogurt",
          "quantity": "150g",
          "target_calories": 59,
          "protein_g": 10,
          "carbs_g": 3.6,
          "fat_g": 0.7
        }
      ],
      "total_macros": {
        "calories": 59,
        "protein_g": 10,
        "carbs_g": 3.6,
        "fat_g": 0.7
      }
    }
  ],
  "total_planned_macros": {
    "calories": 442,
    "protein_g": 46.6,
    "carbs_g": 27,
    "fat_g": 18.8
  },
  "remaining_budget": {
    "calories": 750,
    "protein_g": 63,
    "carbs_g": 217,
    "fat_g": 46.2
  },
  "trigger_used": "user_request",
  "binge_recovery_message": null
}
```

**Trigger Meanings:**
- `user_request`: User manually asked for a plan
- `daily_routine`: Automatic plan generation (e.g., 7am breakfast, 12pm lunch)
- `binge_recovery`: User over-ate yesterday, plan scaled down to recover
- `inventory_expiry`: Suggest meals to use expiring items

---

### POST /meal/suggest-from-inventory — Meal Suggestions from Inventory
Quick meal suggestions based only on what's in the user's fridge/pantry.

**Request:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response:** `200 OK`
```json
{
  "suggestions": [
    {
      "meal_name": "Stir-fried vegetables with tofu",
      "ingredients_from_inventory": [
        "broccoli",
        "bell pepper",
        "tofu",
        "olive oil"
      ],
      "estimated_macros": {
        "calories": 320,
        "protein_g": 18,
        "carbs_g": 22,
        "fat_g": 15
      },
      "missing_items": ["soy sauce", "garlic"]
    }
  ],
  "message": "Based on 12 items currently in your inventory."
}
```

---

### GET /meal/context/{user_id} — Debug: Full Context
Returns the complete knowledge base context for a user (all history aggregated).

**Note:** Development only. Auth-gate or remove before production.

**Response:** `200 OK` (complex nested structure — see history data)

---

## Meal Plans

### POST /plan/generate — Generate Meal Plan
Generate a meal plan **without** automatically saving it. User can review before accepting.

**Request:**
```json
{
  "trigger": "user_request",  // Optional, defaults to "user_request"
  "save": true                 // If true, save to meal_plans table
}
```

**Response:** `200 OK`
```json
{
  "meals": [...],  // Same structure as /meal/plan response
  "plan_id": "550e8400-e29b-41d4-a716-446655442222"  // if save=true
}
```

---

### POST /plan/accept/{plan_id} — Accept a Suggested Plan
Mark a generated plan as active (user taps "Follow this plan").

**Request:** (empty body)

**Response:** `200 OK`
```json
{
  "accepted": true,
  "plan_id": "550e8400-e29b-41d4-a716-446655442222"
}
```

---

### GET /plan/active/{user_id} — Get Today's Active Plan
Fetch the current day's active meal plan (for home screen).

**Request Headers:**
```
Authorization: Bearer {access_token}
```

**Response:** `200 OK`
```json
{
  "active_plan": {
    "meals": [...],  // Meal plan structure
    "plan_id": "550e8400-e29b-41d4-a716-446655442222",
    "plan_date": "2026-04-24"
  }
}
```

**If no active plan:**
```json
{
  "active_plan": null
}
```

---

### POST /plan/revise-week — Revise Weekly Plan (Binge Recovery)
**Core differentiator:** Recalculate plans for remaining week to rebalance after a binge.

Looks at total calories Mon–today, calculates how far over/under the weekly target, then generates revised plans for each remaining day to redistribute without starving the user.

**Request:** (empty body, uses current user)

**Response:** `200 OK`
```json
{
  "week_summary": {
    "from_date": "2026-04-21",
    "to_date": "2026-04-27",
    "days_completed": 3,
    "actual_calories": 9500,
    "target_calories": 7800,
    "overage": 1700
  },
  "revised_plans": {
    "2026-04-24": {  // Today
      "target_calories": 1800,  // Reduced to rebalance
      "meals": [...]
    },
    "2026-04-25": {
      "target_calories": 1850,
      "meals": [...]
    },
    "2026-04-26": {
      "target_calories": 1900,
      "meals": [...]
    },
    "2026-04-27": {
      "target_calories": 1900,
      "meals": [...]
    }
  },
  "message": "You've been 1700 kcal over this week. We've adjusted the next 4 days to ease back to target. You're not punished—we'll get you back on track together."
}
```

---

## Inventory Management

### POST /inventory/add — Add Item to Inventory
Add food item to user's fridge/pantry.

**Request:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Chicken Breast",
  "quantity": "500g",
  "expiry_date": "2026-05-10",
  "category": "protein"  // "protein" | "vegetable" | "dairy" | "grain" | "spice" | "fruit" | "other"
}
```

**Response:** `200 OK`
```json
{
  "item_id": "770e8400-e29b-41d4-a716-446655443333",
  "name": "Chicken Breast",
  "days_until_expiry": 16
}
```

---

### GET /inventory/{user_id} — Get User's Inventory
Fetch all items (filtered to available=true, sorted by expiry date).

**Request Headers:**
```
Authorization: Bearer {access_token}
```

**Response:** `200 OK`
```json
{
  "items": [
    {
      "id": "770e8400-e29b-41d4-a716-446655443333",
      "name": "Chicken Breast",
      "quantity": "500g",
      "category": "protein",
      "expiry_date": "2026-05-10",
      "days_until_expiry": 16,
      "expiring_soon": false
    },
    {
      "id": "880e8400-e29b-41d4-a716-446655444444",
      "name": "Spinach",
      "quantity": "200g",
      "category": "vegetable",
      "expiry_date": "2026-04-26",
      "days_until_expiry": 2,
      "expiring_soon": true
    }
  ],
  "total_items": 12,
  "expiring_soon_count": 2
}
```

**Note:** `expiring_soon` = true if expires in ≤ 3 days.

---

### PATCH /inventory/{item_id} — Update Inventory Item
Update quantity, expiry date, or availability status.

**Request:**
```json
{
  "quantity": "400g",
  "expiry_date": "2026-05-15",
  "is_available": true
}
```

**Response:** `200 OK`
```json
{
  "updated": true,
  "item_id": "770e8400-e29b-41d4-a716-446655443333"
}
```

---

## History & Analytics

### GET /history/{user_id}/daily — Daily Summary Trend
Fetch daily macro summaries for trend viewing (e.g., 7-day chart). Returns pre-aggregated data.

**Query Parameters:**
- `days`: Number of days to retrieve (default: 7, max: 30)

**Request:**
```
GET /history/{user_id}/daily?days=7
```

**Response:** `200 OK`
```json
{
  "days": [
    {
      "date": "2026-04-18",
      "calories": 2100,
      "protein_g": 145,
      "carbs_g": 230,
      "fat_g": 68,
      "fiber_g": 22,
      "meals_logged": 3,
      "is_binge_day": false,
      "target_calories": 2200,
      "vs_target": -100
    },
    {
      "date": "2026-04-19",
      "calories": 2850,
      "protein_g": 165,
      "carbs_g": 310,
      "fat_g": 85,
      "fiber_g": 28,
      "meals_logged": 4,
      "is_binge_day": true,
      "target_calories": 2200,
      "vs_target": 650
    }
  ],
  "streak": 5,  // Consecutive days with ≥ 1 meal logged
  "period": {
    "from": "2026-04-18",
    "to": "2026-04-24"
  }
}
```

**Use Cases:** Weekly calorie chart, macro trend, streak tracking

---

### GET /history/{user_id}/logs — Food Logs for Specific Date
Fetch all food logs for a given date.

**Query Parameters:**
- `date`: ISO date string (default: today). Format: `YYYY-MM-DD`

**Request:**
```
GET /history/{user_id}/logs?date=2026-04-24
```

**Response:** `200 OK`
```json
{
  "date": "2026-04-24",
  "logs": [
    {
      "log_id": "660e8400-e29b-41d4-a716-446655441111",
      "meal_type": "breakfast",
      "logged_at": "2026-04-24T09:15:30",
      "source": "image",
      "description": "Oatmeal with berries and honey",
      "image_url": "https://s3.amazonaws.com/bucket/image123.jpg",
      "food_items": [
        {
          "name": "Oatmeal",
          "quantity": "40g",
          "calories": 150,
          "protein_g": 5,
          "carbs_g": 27,
          "fat_g": 3
        }
      ],
      "macros": {
        "calories": 280,
        "protein_g": 8,
        "carbs_g": 45,
        "fat_g": 5,
        "fiber_g": 4
      },
      "ai_confidence": 0.88,
      "usda_validation": {
        "matched": true
      }
    }
  ],
  "total_logs": 3
}
```

---

### DELETE /history/log/{log_id} — Delete Food Log
Remove a food log entry. Macros automatically reverted from daily summary and binge status recalculated.

**Request:** (empty body)

**Response:** `200 OK`
```json
{
  "deleted": true,
  "log_id": "660e8400-e29b-41d4-a716-446655441111"
}
```

---

### PATCH /history/log/{log_id} — Edit Food Log
Adjust macros for a logged meal (e.g., user realizes portion was different).

**Request:**
```json
{
  "calories": 250,
  "protein_g": 7,
  "carbs_g": 42,
  "fat_g": 4,
  "fiber_g": 3,
  "meal_type": "breakfast"
}
```

**Response:** `200 OK`
```json
{
  "updated": true,
  "log_id": "660e8400-e29b-41d4-a716-446655441111",
  "new_daily_totals": {
    "calories": 1200,
    "protein_g": 85,
    "carbs_g": 140,
    "fat_g": 30
  }
}
```

---

## Utilities

### POST /utils/water — Log Water Intake
Log water consumption (in milliliters).

**Request:**
```json
{
  "amount_ml": 500  // Common: 250 (glass), 500 (bottle), 330 (can)
}
```

**Response:** `200 OK`
```json
{
  "logged_ml": 500,
  "total_ml": 2100,
  "target_ml": 2500,
  "remaining_ml": 400,
  "progress_pct": 84
}
```

---

### GET /utils/water/{user_id} — Get Water Total for Today
Fetch today's cumulative water intake.

**Request Headers:**
```
Authorization: Bearer {access_token}
```

**Response:** `200 OK`
```json
{
  "total_ml": 2100,
  "target_ml": 2500,
  "remaining_ml": 400,
  "progress_pct": 84
}
```

---

### POST /utils/device-token — Register APNs Device Token
Store iOS device token for push notifications (called after user grants permission).

**Request:**
```json
{
  "device_token": "abcd1234efgh5678ijkl9012mnop3456"
}
```

**Response:** `200 OK`
```json
{
  "registered": true,
  "device_token": "abcd1234efgh5678ijkl9012mnop3456"
}
```

---

### GET /utils/micros/{user_id} — Today's Micronutrient Breakdown
Fetch micronutrient summary (vitamins, minerals, etc.).

**Request Headers:**
```
Authorization: Bearer {access_token}
```

**Response:** `200 OK`
```json
{
  "vitamins": {
    "vitamin_a_mcg": 850,
    "vitamin_c_mg": 95,
    "vitamin_d_mcg": 12,
    "vitamin_b12_mcg": 2.4
  },
  "minerals": {
    "calcium_mg": 950,
    "iron_mg": 12,
    "magnesium_mg": 350,
    "potassium_mg": 3400,
    "zinc_mg": 8
  },
  "targets": {
    "calcium_mg": 1000,
    "iron_mg": 8,
    "magnesium_mg": 400,
    "potassium_mg": 3500,
    "zinc_mg": 11
  }
}
```

---

## Error Handling

All errors follow this format:

**Response:** `4xx/5xx`
```json
{
  "detail": "Error message describing the problem"
}
```

**Common Status Codes:**

| Status | Meaning |
|--------|---------|
| `200` | Success |
| `201` | Resource created |
| `400` | Bad request (missing/invalid fields) |
| `401` | Unauthorized (invalid/expired token) |
| `403` | Forbidden (accessing another user's data) |
| `404` | Not found (resource doesn't exist) |
| `429` | Too many requests (rate limit exceeded) |
| `502` | Bad gateway (external service failed, e.g., AI analysis) |

**Rate Limiting Response:**
```json
{
  "detail": "Too many requests. Slow down a little."
}
```

---

## Implementation Notes for iOS

### Token Management
1. Store both `access_token` and `refresh_token` in **Keychain**
2. Include `access_token` in `Authorization: Bearer {token}` header for all authenticated requests
3. On 401 response:
   - Attempt to refresh using `POST /auth/refresh` with `refresh_token`
   - If refresh succeeds → retry original request with new token
   - If refresh fails → clear Keychain, show login screen

### App Launch Flow
1. Check if tokens exist in Keychain
2. If yes → `GET /auth/me` to verify validity
   - If 200 → go to home
   - If 401 → refresh then retry `/auth/me`
   - If refresh fails → show login
3. If no tokens → show login/signup screen

### Image Handling
- For meal logging: Convert image to **base64** string with media type prefix (e.g., `data:image/jpeg;base64,...`)
- Alternatively: Upload image separately to S3, get URL, pass `image_url` in log request

### Data Persistence
- Store locally on device: `user_id`, last login timestamp, selected goals, dietary preferences
- Refresh full profile on app launch via `/auth/me`

### UI Indicators
- **Binge Alert:** If `binge_alert: true` in meal log response → show warning and offer binge-recovery meal plan
- **Expiring Soon:** In inventory, highlight items with `expiring_soon: true`
- **Daily Rings:** Use `/history/{user_id}/daily` response to build circular progress indicators for calories/macros
- **Streak:** Display consecutive days from history endpoint

---

**API Version:** 0.2.0  
**Last Updated:** 2026-04-24

---

## Android POC Addendum

These endpoints support the new Android POC flows without changing the original `/meal/log` behavior.

### POST /meal/analyze
Analyze a meal without saving it. Use this for the review/edit screen.

### POST /meal/log-reviewed
Save a user-confirmed or user-corrected meal result after review.

### POST /meal/what-can-i-eat-now
Return immediate meal/snack options using remaining calories, protein gap, inventory, expiring items, and dietary restrictions.

### GET /coach/today
Return a fast deterministic home-screen coach card with progress and action metadata.

