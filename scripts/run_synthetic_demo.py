"""Explicit synthetic-demo API. Not the production or ordinary local entrypoint.

Builds a temporary SQLite from the existing synthetic fixture and serves the
four real pipelines through ``create_app(container=demo_container)``. Default
``build_container`` is never called.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from tests.integration.four_mode_synthetic_container import (  # noqa: E402
    create_synthetic_demo_app,
)

DEMO_HOST = "127.0.0.1"
DEMO_PORT = 8000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the synthetic four-mode browser demo.")
    parser.add_argument("--host", default=DEMO_HOST)
    parser.add_argument("--port", type=int, default=DEMO_PORT)
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="insightmatch-synthetic-demo-") as tmp:
        database_path = Path(tmp) / "synthetic.db"
        print(
            "Synthetic demo API — 合成数据演示，不是马克思恩格斯原典.",
            file=sys.stderr,
        )
        print(f"Listening on http://{args.host}:{args.port} (reload disabled).", file=sys.stderr)
        app = create_synthetic_demo_app(database_path)
        uvicorn.run(app, host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
