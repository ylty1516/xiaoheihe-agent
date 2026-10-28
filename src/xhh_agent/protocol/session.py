"""会话（Cookie）的持久化。

Cookie 等价于账号密码，因此：
- 只允许落在 ``.data/`` 下
- 文件权限收到 0600
- ``Session.__repr__`` 不输出 cookie，避免被日志带出去
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .errors import LoginExpired

#: 上游使用的默认设备 ID。不要随机生成——每换一次 device_id 就相当于新设备，
#: 徒增风控信号。
DEFAULT_DEVICE_ID = "02f61cdb0c14c026f9e6865d7744b86e"


@dataclass(frozen=True)
class Session:
    cookie: str
    heybox_id: str
    device_id: str = DEFAULT_DEVICE_ID

    def __repr__(self) -> str:  # pragma: no cover - 简单字符串拼接
        return f"Session(heybox_id={self.heybox_id!r}, device_id={self.device_id!r})"

    __str__ = __repr__


class SessionStore:
    """读写会话文件。默认路径由调用方传入（通常 ``.data/session.json``）。"""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def save(self, session: Session) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cookie": session.cookie,
            "heybox_id": session.heybox_id,
            "device_id": session.device_id,
        }
        # 以 0600 直接创建，避免 write_text 之后、chmod 之前那段 0644 窗口。
        # 注意：Windows 会忽略 mode 中的权限位（只影响只读属性），
        # 因此 Windows 上仍需依赖目录 ACL，残余风险已写入 README。
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def load(self) -> Session:
        if not self.path.exists():
            raise LoginExpired(f"未找到会话文件 {self.path}，请先运行 'xhh login'")
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            # 只报异常类型，不回显文件内容（里面是 cookie）
            raise LoginExpired(
                f"会话文件无法解析（{type(exc).__name__}），请重新运行 'xhh login'"
            ) from None

        cookie = str(data.get("cookie") or "")
        if not cookie:
            raise LoginExpired("会话文件缺少 cookie，请重新运行 'xhh login'")

        return Session(
            cookie=cookie,
            heybox_id=str(data.get("heybox_id") or ""),
            device_id=str(data.get("device_id") or DEFAULT_DEVICE_ID),
        )
