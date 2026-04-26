#!/usr/bin/env python3
"""
run_tests.py
────────────
Convenient test runner with shortcuts.

Usage:
  python run_tests.py              # run all tests
  python run_tests.py auth         # run only auth tests
  python run_tests.py users        # run only user tests
  python run_tests.py meals        # run only meal logging tests
  python run_tests.py inventory    # run only inventory tests
  python run_tests.py history      # run only history tests
  python run_tests.py plans        # run only plan tests
  python run_tests.py utils        # run only utils + agents tests
  python run_tests.py --fast       # skip slow AI-heavy tests
  python run_tests.py --url http://staging.example.com  # test against staging

Environment variables:
  TEST_BASE_URL=http://localhost:8000  (default)
"""

import sys
import os
import subprocess

MODULE_MAP = {
    "auth":      "tests/test_01_auth.py",
    "users":     "tests/test_02_users.py",
    "meals":     "tests/test_03_meal_logging.py",
    "inventory": "tests/test_04_inventory.py",
    "history":   "tests/test_05_history.py",
    "plans":     "tests/test_06_meal_plans.py",
    "utils":     "tests/test_07_utils.py",
}

def main():
    args = sys.argv[1:]
    pytest_args = ["pytest"]

    # Handle --url flag
    if "--url" in args:
        idx = args.index("--url")
        url = args[idx + 1]
        os.environ["TEST_BASE_URL"] = url
        args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]
        print(f"  Testing against: {url}")

    # Handle --fast flag
    if "--fast" in args:
        pytest_args += ["-m", "not slow"]
        args.remove("--fast")

    # Handle specific module
    if args and args[0] in MODULE_MAP:
        pytest_args.append(MODULE_MAP[args[0]])
    elif args:
        pytest_args += args
    else:
        pytest_args.append("tests/")

    # Always show summary
    pytest_args += ["--tb=short", "-v"]

    print(f"Running: {' '.join(pytest_args)}\n")
    result = subprocess.run(pytest_args)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()