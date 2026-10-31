"""Load the bundled sample notes into a running PaperDesk instance.

Usage: python scripts/seed.py [--api http://127.0.0.1:8080]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"

META = {
    "transformer_note.pdf": {"venue": "NeurIPS", "field": "自然语言处理", "year": 2017, "has_code": True},
    "rag_note.pdf": {"venue": "NeurIPS", "field": "信息检索", "year": 2020, "has_code": True},
    "gnn_note.pdf": {"venue": "ICLR", "field": "图学习", "year": 2019, "has_code": False},
    "peft_note.pdf": {"venue": "ICLR", "field": "模型训练", "year": 2021, "has_code": True},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    for path in sorted(SAMPLES.glob("*.pdf")):
        meta = META.get(path.name, {})
        with path.open("rb") as handle:
            response = httpx.post(
                f"{args.api}/api/papers/upload",
                files={"file": (path.name, handle, "application/pdf")},
                data={
                    "venue": meta.get("venue", ""),
                    "field": meta.get("field", ""),
                    "year": str(meta.get("year", "")),
                    "has_code": str(meta.get("has_code", False)).lower(),
                },
                timeout=120.0,
            )
        if response.status_code == 409:
            print(f"skip  {path.name} (已存在)")
            continue
        if response.status_code >= 400:
            print(f"fail  {path.name} -> {response.status_code} {response.text[:200]}")
            return 1
        data = response.json()
        print(f"ok    {path.name} -> {data['chunks']} chunks / {data['pages']} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
