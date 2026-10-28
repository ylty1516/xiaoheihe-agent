"""把 HTML 里内嵌的 base64 图片替换成图床 URL。

背景：转换器把代码块和表格渲染成 ``data:image/png;base64,...`` 直接内嵌。
发帖时服务端会拒这种 src（"图片链接不合法"），必须先上传拿 URL。
"""

from __future__ import annotations

import base64
import io
import re
from typing import Any

DATA_URI_RE = re.compile(
    r"data:image/(png|jpeg|jpg|gif|webp);base64,([A-Za-z0-9+/=\s]+)",
    re.IGNORECASE,
)


def _image_size(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:  # noqa: BLE001 - 尺寸只是元数据，读不到就给 0
        return (0, 0)


async def replace_inline_images(html: str, uploader: Any) -> tuple[str, int]:
    """把每个 data URI 上传成 URL 并替换。返回 (新 HTML, 上传张数)。"""
    parts: list[str] = []
    position = 0
    uploaded = 0

    for match in DATA_URI_RE.finditer(html):
        subtype = match.group(1).lower()
        encoded = match.group(2)
        try:
            payload = base64.b64decode(encoded)
        except (ValueError, TypeError):
            # 解不开就原样保留，让服务端明确拒绝，而不是静默丢掉一张图
            continue

        parts.append(html[position : match.start()])
        width, height = _image_size(payload)
        url = await uploader.upload(
            data=payload,
            name=f"inline-{uploaded + 1}.{subtype}",
            mimetype=f"image/{subtype}",
            width=width,
            height=height,
        )
        parts.append(url)
        position = match.end()
        uploaded += 1

    parts.append(html[position:])
    return "".join(parts), uploaded
