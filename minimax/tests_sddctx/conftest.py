"""上下文模块自身的单元测试（不依赖外部服务）。

    cd minimax && python -m pytest -q tests_sddctx
"""

from __future__ import annotations

import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))
