# NutriAI Test Suite

## Structure

```
tests/
├── conftest.py              # Shared fixtures, State object, base config
├── test_01_auth.py          # Signup, login, token refresh, /me
├── test_02_users.py         # Profile GET/PUT, macro recalculation
├── test_03_meal_logging.py  # Food logging, macros, USDA validation, context
├── test_04_inventory.py     # Add/get/update/delete items, image scan, suggestions
├── test_05_history.py       # Daily history, log list, edit log, delete log
├── test_06_meal_plans.py    # Generate plan, accept, active plan, week revision
└── test_07_utils.py         # Water, device token, micros, agents, rate limit
```

## Prerequisites

```bash
# 1. Server must be running
uvicorn app.main:app --reload

# 2. Install test dependencies
pip install pytest httpx

# 3. Postgres must be running (docker-compose up -d)
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# Single module
pytest tests/test_01_auth.py -v

# Via shortcut script
python run_tests.py
python run_tests.py auth
python run_tests.py meals

# Against staging/production
python run_tests.py --url http://your-server.com

# Skip slow AI tests
python run_tests.py --fast

# Show print output
pytest tests/ -v -s

# Stop on first failure
pytest tests/ -v -x

# Run specific test
pytest tests/test_03_meal_logging.py::TestMealLogging::test_01_log_banana_text -v
```

## How tests share state

Tests run in order (01 → 07) and share a single `State` object via the
`shared_state` fixture. The signup in `test_01_auth.py` populates:
- `state.access_token` — used by all subsequent tests
- `state.user_id` — used for all user-specific endpoints
- `state.banana_log_id` — used by history tests to edit/delete
- `state.plan_id` — used by plan tests to accept

Each full run creates a **fresh user** with a unique email so re-runs
never conflict with each other.

## Adding new tests

### New endpoint in an existing module
Add a `test_XX_name` function to the relevant class. Follow existing patterns.

### New feature module
1. Create `tests/test_08_feature.py`
2. Add `class TestFeature:` with `test_XX_` methods
3. Use `shared_state` for any tokens/IDs you need
4. Add the module to `MODULE_MAP` in `run_tests.py`

### New shared state field
Add the field to the `State` class in `conftest.py`:
```python
class State:
    my_new_id: str = ""
```

## Test philosophy

- **Order matters** — tests build on each other's state
- **No mocking** — tests hit the real running server (integration tests)
- **Auth on everything** — every protected endpoint is tested with and without token
- **403 checks** — cross-user access is explicitly tested for sensitive endpoints
- **Defensive assertions** — use `in response` checks, not exact value matches
  for AI-generated content (calories may vary slightly between runs)