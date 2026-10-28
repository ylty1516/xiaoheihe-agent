"""把几行文字做成轮播动图。

找不到合适 gif 的时候用这个自己造喵。比如把「四个差评点」做成 4 帧轮播，
比堆四张静态图更有节奏感喵。

用法：
    py scripts/make_gif.py --out .data/anim.gif --title "幕府2翻车四件事" \
        --line "性能倒退" --line "崩溃新Bug" --line "模组报废" --line "AI画面"

生成的文件可以直接写进 Markdown：``![动图](.data/anim.gif)``，
发帖时会自动上传到小黑盒图床喵。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: 常见中文字体，找不到就退回默认字体（英文数字能显示，中文会变方块）
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

BG = (24, 26, 32)
ACCENT = (229, 72, 77)
TEXT = (245, 245, 245)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def build_gif(*, out: Path, title: str, lines: list[str], size=(600, 360), ms=900) -> Path:
    width, height = size
    title_font = _load_font(26)
    line_font = _load_font(40)
    frames: list[Image.Image] = []

    # 第一帧：标题
    img = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 6], fill=ACCENT)
    draw.text((40, height // 2 - 20), title, font=title_font, fill=TEXT)
    frames.append(img)

    # 后面每帧一条
    for index, line in enumerate(lines, start=1):
        img = Image.new("RGB", size, BG)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, width, 6], fill=ACCENT)
        draw.text((40, 34), f"{index}/{len(lines)}", font=title_font, fill=ACCENT)
        draw.text((40, height // 2 - 26), line, font=line_font, fill=TEXT)
        frames.append(img)

    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out, save_all=True, append_images=frames[1:], duration=ms, loop=0, optimize=True
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="文字轮播动图生成")
    parser.add_argument("--out", required=True, help="输出路径，如 .data/anim.gif")
    parser.add_argument("--title", required=True, help="首帧标题")
    parser.add_argument("--line", action="append", required=True, help="每帧一句，可重复")
    parser.add_argument("--ms", type=int, default=900, help="每帧毫秒数")
    args = parser.parse_args()

    path = build_gif(out=Path(args.out), title=args.title, lines=args.line, ms=args.ms)
    image = Image.open(path)
    print(f"已生成 {path}  {image.size[0]}x{image.size[1]}  {image.n_frames} 帧  "
          f"{path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
