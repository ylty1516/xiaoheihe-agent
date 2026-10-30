"""本地 Web 面板：``xhh auto`` 打开的界面。"""

from .app import create_app, serve
from .state import build_state

__all__ = ["build_state", "create_app", "serve"]
