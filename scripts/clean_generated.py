"""Remove only documented generated development artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / ".pytest_cache", ROOT / ".ruff_cache", ROOT / ".mypy_cache"]


def main() -> int:
    for target in TARGETS:
        if target.is_dir():
            shutil.rmtree(target)
    print("Removed generated development caches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
