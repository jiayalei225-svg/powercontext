"""生成交付用上下文快照（artifacts/context/context.json）。

    python scripts/build_context.py --task samples/task.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE_ROOT))

from sddctx.config import Settings  # noqa: E402
from sddctx.selector import ContextBuilder  # noqa: E402
from sddctx.state import PowerContextState  # noqa: E402
from sddctx.store import SeekDBStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成上下文快照")
    parser.add_argument("--task", default="samples/task.json")
    parser.add_argument("--out", default="artifacts/context/context.json")
    args = parser.parse_args(argv)

    settings = Settings.load()
    task = json.loads((MODULE_ROOT / args.task).read_text(encoding="utf-8"))
    store = SeekDBStore(settings.seekdb_path, query_log=settings.query_log)
    state = PowerContextState(settings.powercontext_url, settings.state_dir)
    context = ContextBuilder(store, state, budget_bytes=settings.budget_bytes).build(task)
    context["seekdb"] = store.stats()

    out = MODULE_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(context['spec_items'])} specs, {len(context['code_targets'])} code, "
          f"{len(context['tests']['functional']) + len(context['tests']['regression'])} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
