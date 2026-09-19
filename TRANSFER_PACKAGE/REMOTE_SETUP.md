# Remote Setup & Execution Guide: temporal-feature-repair

This guide provides exact, copy-pasteable instructions to unpack, inspect, build, run, and validate the `temporal-feature-repair` benchmark task on a remote evaluation machine without hard-coded local paths.

---

## 1. Verify Archive Integrity

Upon receiving the `TRANSFER_PACKAGE/` directory, verify that the archive has not been corrupted:

```bash
cd TRANSFER_PACKAGE
sha256sum -c checksum.sha256
```

Expected output:
```
temporal-feature-repair.tar.gz: OK
```

---

## 2. Extract into Target Harbor / Benchmark Directory

Extract the task into your desired Harbor repository tasks directory (e.g. `harbor/tasks/` or standalone):

```bash
tar -xzvf temporal-feature-repair.tar.gz -C /path/to/harbor/tasks/
cd /path/to/harbor/tasks/temporal-feature-repair
```

---

## 3. Tooling Prerequisites

The remote machine requires:
- **Python >= 3.10**
- **Docker** or **Podman** container runtime
- **Harbor** framework (`pip install harbor` or `uv tool install harbor`)

To verify the installed Harbor environment:
```bash
harbor --version
```

---

## 4. Validate Task Schema & Rubric Invariants

Run static schema and rubric validation using Harbor and Python:

```bash
python3 -c "
import tomllib
from pathlib import Path
import harbor.models.task.config as c

task_cfg = c.TaskConfig.model_validate(tomllib.loads(Path('task.toml').read_text()))
print('Task Schema Valid:', task_cfg.task.name)
"
```

---

## 5. Build Environment Container

Build the agent runtime Docker container cleanly:

```bash
docker build -t harbor-temporal-feature-repair:latest environment/
```

---

## 6. Execute Baseline (Flawed Starting State / NOP)

To verify that the unmodified, flawed starting state properly fails verification:

```bash
# Keep output, warehouse, and verifier logs across the separate containers.
RUNTIME_DIR="$(mktemp -d)"

# Run the pipeline inside the container
docker run --rm \
  -v "$(pwd)/environment/src:/app/src" \
  -v "$(pwd)/environment/data:/app/data:ro" \
  -v "$RUNTIME_DIR/output:/app/output" \
  -v "$RUNTIME_DIR/warehouse:/app/warehouse" \
  harbor-temporal-feature-repair:latest \
  python3 /app/src/pipeline/main.py

# Run the test suite against flawed output
docker run --rm \
  -v "$(pwd)/tests:/tests:ro" \
  -v "$RUNTIME_DIR/output:/app/output" \
  -v "$RUNTIME_DIR/logs:/logs" \
  harbor-temporal-feature-repair:latest \
  bash /tests/test.sh

cat "$RUNTIME_DIR/logs/verifier/reward.txt"  # Output: 0
```

---

## 7. Execute Oracle Solution (Reference Solution)

To execute the reference oracle solution and verify that it passes 100% of the tests:

```bash
# Use a fresh persistent runtime directory for the oracle and verifier pair.
RUNTIME_DIR="$(mktemp -d)"

# Run oracle solution
docker run --rm \
  -v "$(pwd)/solution:/app/solution:ro" \
  -v "$(pwd)/environment/data:/app/data:ro" \
  -v "$RUNTIME_DIR/output:/app/output" \
  harbor-temporal-feature-repair:latest \
  bash /app/solution/solve.sh

# Run verifier test suite
docker run --rm \
  -v "$(pwd)/tests:/tests:ro" \
  -v "$RUNTIME_DIR/output:/app/output" \
  -v "$RUNTIME_DIR/logs:/logs" \
  harbor-temporal-feature-repair:latest \
  bash /tests/test.sh

cat "$RUNTIME_DIR/logs/verifier/reward.txt"  # Output: 1
```

---

## 8. Run via Harbor Harness

You can also run the complete task via Harbor CLI:

```bash
# Run oracle trial
harbor trial start -p . -a oracle

# Run agent trial (e.g. claude-code or custom agent)
harbor trial start -p . -a claude-code -m claude-sonnet-4-6
```
