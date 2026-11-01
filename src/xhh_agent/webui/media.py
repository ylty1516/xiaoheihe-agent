"""Local image attachments and a sanitized, network-free Markdown preview."""

from __future__ import annotations

import html
import io
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import markdown
from PIL import Image

MAX_IMAGE_BYTES = 8 * 1024 * 1024
FORMATS = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}


def media_path(root: Path, name: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}\.(png|jpg|gif|webp)", name):
        raise ValueError("图片名称无效")
    base = (root / ".data").resolve()
    folder = base / "media"
    path = folder / name
    if folder.resolve().parent != base or path.resolve().parent != folder.resolve():
        raise ValueError("图片路径无效")
    return path


def save_image(root: Path, content: bytes) -> dict:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片为空或超过 8 MB")
    try:
        with Image.open(io.BytesIO(content)) as img:
            extension = FORMATS.get(img.format)
            if not extension or img.width * img.height > 30_000_000:
                raise ValueError("仅支持 PNG/JPG/GIF/WebP，图片尺寸不能超过 3000 万像素")
            img.verify()
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("文件不是有效图片") from exc
    name = f"{uuid.uuid4().hex}.{extension}"
    path = media_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {"ok": True, "markdown": f"![配图](.data/media/{name})", "url": f"/api/media/{name}"}


def publication_markdown(root: Path, text: str) -> str:
    """Resolve managed attachments independently of the process working directory."""

    def replace(match):
        path = media_path(root, match[2])
        if not path.is_file():
            raise ValueError("稿件引用的配图不存在，请重新上传")
        return f"![{match[1]}](<{path.as_posix()}>)"

    return re.sub(
        r"!\[([^\]]*)\]\(\.data/media/([0-9a-f]{32}\.(?:png|jpg|gif|webp))\)", replace, text
    )


class Preview(HTMLParser):
    ALLOWED = {
        "p",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "strong",
        "em",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
        "del",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in self.ALLOWED:
            self.parts.append(f"<{tag}>")
        elif tag == "img":
            src = values.get("src", "") or ""
            match = re.fullmatch(r"(?:\.data/)?media/([0-9a-f]{32}\.(?:png|jpg|gif|webp))", src)
            if match:
                self.parts.append(
                    f'<img src="/api/media/{match[1]}" alt="{html.escape(values.get("alt", "") or "", quote=True)}">'
                )
            else:
                self.parts.append(
                    '<span class="image-placeholder">[配图：'
                    + html.escape(values.get("alt", "") or "外部图片")
                    + "；外部图片在发布时转存]</span>"
                )
        elif tag == "a":
            href = values.get("href", "") or ""
            try:
                safe = urlsplit(href).scheme in {"http", "https"}
            except ValueError:
                safe = False
            self.parts.append(
                f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">'
                if safe
                else "<span>"
            )
            self.links.append("a" if safe else "span")

    def handle_endtag(self, tag):
        if tag in self.ALLOWED and tag not in {"br", "hr"}:
            self.parts.append(f"</{tag}>")
        elif tag == "a":
            # Unknown links have no active attributes, and unmatched closing tags
            # cannot introduce markup or scripts.
            if self.links:
                self.parts.append(f"</{self.links.pop()}>")

    def handle_data(self, data):
        self.parts.append(html.escape(data))


def render_preview(text: str) -> str:
    if not isinstance(text, str) or len(text) > 200_000:
        raise ValueError("正文过长或格式无效")
    renderer = Preview()
    renderer.feed(markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists"]))
    return "".join(renderer.parts)
