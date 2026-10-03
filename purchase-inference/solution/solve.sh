#!/bin/bash
set -euo pipefail

# The Oracle is an independent implementation. Install its executable entry
# point only during the Oracle agent phase so Harbor's later collect hook can
# exercise the same public path that a normal repaired task supplies.
cp /solution/reference_analysis.py /app/src/pipeline/main.py
python3 /app/src/pipeline/main.py --data /app/data --output /app/output
