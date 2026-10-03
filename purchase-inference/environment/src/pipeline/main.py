"""Starter entry point for the required deterministic scientific pipeline.

Implement the procedure in instruction.md. The verifier invokes this public entry
point again after a completed run to assess deterministic stability.
"""

from __future__ import annotations


def run_pipeline() -> None:
    raise SystemExit(
        "Implement the exposure-aware Poisson analysis described in /app/instruction.md "
        "and write the required artifacts to /app/output."
    )


if __name__ == "__main__":
    run_pipeline()
