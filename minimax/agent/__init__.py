"""Agent 接入层：把 sddctx 的上下文交给 MiniMax，落地代码并记录开发日志。"""

from .minimax_client import MiniMaxClient, MiniMaxError

__all__ = ["MiniMaxClient", "MiniMaxError"]
