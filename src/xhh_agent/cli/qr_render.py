"""把登录二维码渲染成可扫的图片。

为什么需要这一步：``request_qr_login()`` 返回的 ``qr_url`` 是**二维码内容**，
不是网页。用浏览器打开会 302 到"该功能需要登录使用"，因为
``/account/qr_login/`` 期待的是 App 扫码后的确认请求。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def render_qr(qr_url: str, out_path: str | os.PathLike[str]) -> Path:
    """生成 PNG 二维码并返回路径。需要 ``qrcode[pil]``。"""
    import qrcode

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(path)
    return path


def try_open_image(path: str | os.PathLike[str]) -> bool:
    """用系统默认看图程序打开。失败返回 False，不抛异常。"""
    target = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", target], check=False)
        else:
            subprocess.run(["xdg-open", target], check=False)
        return True
    except Exception:  # noqa: BLE001 - 打开失败不影响扫码（可手动打开文件）
        return False


def cleanup(path: str | os.PathLike[str]) -> None:
    """删除二维码文件。log in 成功后调用，避免 token 留在磁盘上。"""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
