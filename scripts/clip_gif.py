"""从视频里截一段做成 GIF。

用在：官方预告片、实机演示、别人的视频片段——比自己造图真实得多喵。

前置：
- yt-dlp（下视频），可以用任意路径，脚本会自动找
- ffmpeg（转 gif），优先用 imageio-ffmpeg 自带的，避免 PATH 问题

用法：
    py scripts/clip_gif.py --url "https://www.youtube.com/watch?v=xxx" --start 52 --end 58 --out .data/clip.gif
    py scripts/clip_gif.py --local video.mp4 --start 10 --end 14 --out .data/x.gif

参数说明：
--width  宽度，默认 480（小黑盒帖子里够用，文件也不会太大）
--fps    帧率，默认 8（12 以上文件会翻倍）
--colors 调色板颜色数，默认 128（越小文件越小）
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: yt-dlp 可能装在别的虚拟环境里，按顺序找
YTDLP_CANDIDATES = (
    "yt-dlp",
    r"F:\Grok_Workspace\01_Projects\VideoCaptioner\.venv\Scripts\yt-dlp.exe",
)


def find_ytdlp() -> str | None:
    for candidate in YTDLP_CANDIDATES:
        found = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if found:
            return found
    return None


def find_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return shutil.which("ffmpeg")


def run(cmd: list[str], *, quiet: bool = True) -> str:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        encoding="utf-8",
    )
    if result.returncode != 0 and not quiet:
        print(result.stderr[-800:], file=sys.stderr)
    return result.stdout + result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description="从视频截一段做 GIF")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="视频地址（YouTube 等）")
    src.add_argument("--local", help="本地视频文件")
    parser.add_argument("--start", type=float, required=True, help="起始秒")
    parser.add_argument("--end", type=float, required=True, help="结束秒")
    parser.add_argument("--out", required=True, help="输出 gif 路径")
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--colors", type=int, default=128)
    args = parser.parse_args()

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("找不到 ffmpeg，请先 pip install imageio-ffmpeg", file=sys.stderr)
        return 1
    ffmpeg_dir = str(Path(ffmpeg).parent)

    duration = max(0.5, args.end - args.start)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        if args.local:
            video = Path(args.local)
            if not video.exists():
                print(f"本地视频不存在：{video}", file=sys.stderr)
                return 1
        else:
            ytdlp = find_ytdlp()
            if not ytdlp:
                print("找不到 yt-dlp，请先安装", file=sys.stderr)
                return 1
            template = str(tmp_dir / "clip.%(ext)s")
            section = f"*{args.start}-{args.end}"
            print(f"下载 {section} 秒的片段...", flush=True)
            run([
                ytdlp, "--no-warnings", "--ffmpeg-location", ffmpeg_dir,
                "-f", "bv*[height<=720]+ba/b[height<=720]",
                "--download-sections", section,
                "--force-keyframes-at-cuts",
                "-o", template, args.url,
            ])
            candidates = list(tmp_dir.glob("clip.*"))
            if not candidates:
                print("下载失败，没拿到视频文件", file=sys.stderr)
                return 1
            video = candidates[0]

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        vf = (
            f"fps={args.fps},scale={args.width}:-1:flags=lanczos,"
            f"split[a][b];[a]palettegen=max_colors={args.colors}:stats_mode=diff[p];"
            f"[b][p]paletteuse=dither=bayer:bayer_scale=3"
        )
        print("转 GIF...", flush=True)
        run([ffmpeg, "-y", "-i", str(video), "-vf", vf, "-t", f"{duration:.2f}",
             "-loop", "0", str(out)])

    if not out.exists():
        print("转换失败", file=sys.stderr)
        return 1
    size_kb = out.stat().st_size / 1024
    print(f"完成：{out}  {size_kb:.0f} KB")
    if size_kb > 3000:
        print(f"提示：{size_kb/1024:.1f} MB 偏大，上传会慢喵。可以调小 --width 或 --fps 喵")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
