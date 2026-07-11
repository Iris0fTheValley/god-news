from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))


def main() -> None:
    from god_news.main import app

    parser = argparse.ArgumentParser(
        description="Export the authoritative god-news OpenAPI schema."
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    destination: Path = args.output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
