#!/bin/bash
# run_tests.sh - Comprehensive Audit Verification & Regression Suite
# This script ensures the system is compliant with all remediated audit goals.

set -e

# Colors for terminal output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}   Medical Ops API - Audit Compliance Verification Suite   ${NC}"
echo -e "${BLUE}============================================================${NC}"

# 1. Environment Setup
echo -e "\n[1/5] Initializing Test Environment..."
export PYTHONPATH=.
export OFFLINE_MODE=true
# Force local SQLite for standalone verification scripts
export DATABASE_URL="sqlite:///./test_local.db"

# Cleanup any stale test DB from previous failed runs
if [ -f test_local.db ]; then
    rm test_local.db
fi

# Ensure .env exists if not provided
if [ ! -f .env ]; then
    echo "Warning: .env not found. Creating from .env.example..."
    cp .env.example .env
fi

# 2. Migration Integrity Check
echo -e "\n[2/5] Running Database Migrations..."
# This verifies the migration path is unbroken on SQLite.
alembic upgrade head

# 3. Static Remediation Verification
echo -e "\n[3/5] Verifying Static Remediations..."
# Initialize the local DB for scripts
python -m app.db.init_db
python scripts/verify_remediation.py

# 4. Critical Audit Tests
echo -e "\n[4/5] Executing Critical Audit Verification Tests..."
# pytest uses its own internal temp DB, but we keep the env vars for consistency
pytest tests/test_audit_final_verification.py -v --tb=short

# 5. Full Regression Suite
echo -e "\n[5/5] Executing Full Regression Suite..."
pytest --tb=short

# Cleanup local test DB
if [ -f test_local.db ]; then
    rm test_local.db
fi

echo -e "\n${GREEN}============================================================${NC}"
echo -e "${GREEN}   VERIFICATION COMPLETE: ALL AUDIT GOALS PASSED            ${NC}"
echo -e "${GREEN}============================================================${NC}"
