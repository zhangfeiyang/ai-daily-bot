#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.testing.smoke import run_smoke_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a fully mocked pipeline smoke test.")
    parser.add_argument(
        "--workdir",
        default="output/smoke",
        help="Directory for smoke artifacts.",
    )
    args = parser.parse_args()

    result = run_smoke_pipeline(Path(args.workdir))
    print(result.to_dict())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
