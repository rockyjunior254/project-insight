#!/bin/bash
set -euo pipefail

if python3 -m pytest -q /tests/test_outputs.py --maxfail=1; then
  printf '1\n' > /logs/verifier/reward.txt
else
  printf '0\n' > /logs/verifier/reward.txt
fi
