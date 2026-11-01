"""Load the five demo PDFs into seekdb."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import index, pdf  # noqa: E402
from app.settings import settings  # noqa: E402


def ingest(path: Path, force: bool) -> tuple[str, int, bool]:
    data = path.read_bytes()
    paper_id = pdf.digest(data)
    target = settings.upload_dir / f"{paper_id}.pdf"
    if not target.is_file():
        target.write_bytes(data)
    if index.exists(paper_id) and not force:
        return paper_id, 0, True
    pages = pdf.read_pages(path)
    meta = pdf.read_meta(pages, path.name)
    chunks = pdf.split_pages(pages)
    written = index.add(paper_id, meta, chunks)
    return paper_id, written, False


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 samples/ 下的演示语料")
    parser.add_argument("--force", action="store_true", help="已存在的论文也重新分块与向量化")
    parser.add_argument("--samples", type=Path, default=ROOT / "samples", help="样例目录")
    args = parser.parse_args()

    files = sorted(args.samples.glob("*.pdf"))
    if not files:
        raise SystemExit(f"没有找到 PDF：{args.samples}")
    for path in files:
        paper_id, written, skipped = ingest(path, args.force)
        state = "已存在，跳过" if skipped else f"写入 {written} 个片段"
        print(f"{path.name:42s} {paper_id}  {state}")

    stats = index.stats()
    print("")
    print(f"集合 {stats['collection']}：{stats['papers']} 篇论文 / {stats['chunks']} 个片段 / 模型 {stats['embedding']}")
    print(f"数据目录：{settings.data_dir}")


if __name__ == "__main__":
    main()
