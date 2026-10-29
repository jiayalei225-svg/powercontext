"""sddctx —— 面向软件持续演进的 SDD 工程上下文模块。

对外只做三件事：

1. ``ingest``：把规格、代码、测试写入 seekdb（含向量索引）；
2. ``build``：按任务检索并组装开发上下文（规格条目 / 代码符号 / 测试 / 任务进展）；
3. ``state``：把任务进展与验证结果写入 PowerContext 并在下次运行读出。
"""

from .config import Settings
from .ingest import ingest_all, ingest_code, ingest_specs, ingest_tests
from .selector import ContextBuilder
from .state import PowerContextState, StateUnavailable
from .store import SeekDBStore

__all__ = [
    "ContextBuilder",
    "PowerContextState",
    "SeekDBStore",
    "Settings",
    "StateUnavailable",
    "ingest_all",
    "ingest_code",
    "ingest_specs",
    "ingest_tests",
]

__version__ = "1.0.0"
