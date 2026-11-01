"""Import the bundled seed documents without starting the web server.

Usage (from qoder/):
    .venv/Scripts/python scripts/import_seed.py            # Windows
    .venv/bin/python scripts/import_seed.py                # macOS / Linux

Add ``--force`` to rebuild chunks even when the file hash is unchanged.
Stop the app before running this: seekdb is embedded and one writer at a
time is the safe assumption.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.ingest import pipeline  # noqa: E402
from app.seekdb import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Import qoder/data/seed into seekdb")
    parser.add_argument("--force", action="store_true", help="re-chunk even if the hash is unchanged")
    parser.add_argument("--session", default="cli-import", help="trace session id")
    args = parser.parse_args()

    settings.prepare()
    db.init_schema()
    results = pipeline.import_seed(session_id=args.session, force=args.force)
    for item in results:
        state = "skipped" if item["skipped"] else f"{item['chunks']} chunks"
        print(f"{item['doc_id']:28s} {item['subject']:8s} {state}")
    print(pipeline.stats())


if __name__ == "__main__":
    main()
