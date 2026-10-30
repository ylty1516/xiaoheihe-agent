"""发帖自检脚本的测试。

规则是用户钉死的，脚本是让规则能被机械执行的唯一手段。
脚本自己坏掉却还报「通过」，比没有脚本更糟——所以这里重点测
「该拦的必须拦住」，而不是「能跑」。
"""

import subprocess
import sys
from pathlib import Path

import pytest

from xhh_agent.content.stats import (
    MIN_CHARS,
    check_post,
    count_body_chars,
)

ROOT = Path(__file__).resolve().parents[1]

#: 一段够长、不含任何禁用词的正文
BODY = "影之刃零今天解锁，驱动版本和评分是两件不同的事。" * 90
IMAGES = "\n![图一](http://x/1.jpg)\n![图二](http://x/2.jpg)\n![图三](http://x/3.jpg)\n"


def _md(body: str = BODY, images: str = IMAGES, heading: str = "## 驱动比评分麻烦\n") -> str:
    return heading + body + images


# ── count_body_chars ──────────────────────────────────────


def test_images_and_emoji_do_not_count():
    """图注和表情不算字数，否则能靠堆图注凑够 1500。"""
    plain = "字" * 1500
    assert count_body_chars(plain) == 1500
    assert count_body_chars(plain + "![说明文字很长很长](http://x/a.jpg)") == 1500
    assert count_body_chars(plain + "[cube_捂脸哭]") == 1500


def test_whitespace_and_heading_marks_are_ignored():
    """只去 `##` 标记和空白；小标题的文字本身算正文，不能免费。"""
    assert count_body_chars("## \n\n字 字 字\n") == 3
    assert count_body_chars("## 标题\n字\n") == 3          # 2 + 1


# ── check：该拦的必须拦 ────────────────────────────────────


def test_good_post_passes():
    problems, _ = check_post(_md())
    assert count_body_chars(_md()) >= MIN_CHARS
    assert problems == []


def test_short_post_is_rejected():
    problems, _ = check_post(_md(body="太短了喵~" * 5))
    assert any(str(MIN_CHARS) in p for p in problems)


def test_turn_words_are_rejected():
    problems, _ = check_post(_md(body=BODY + "不过我觉得这个设计有问题。"))
    assert any("转折词" in p for p in problems)


def test_too_many_emoji_are_rejected():
    problems, _ = check_post(_md(body=BODY + "[cube_鹅]" * 7))
    assert any("表情" in p for p in problems)


def test_too_many_meow_are_rejected():
    problems, _ = check_post(_md(body=BODY + "喵~" * 5))
    assert any("喵~" in p for p in problems)


def test_too_few_images_are_rejected():
    problems, _ = check_post(_md(images="\n![只有一张](http://x/1.jpg)\n"))
    assert any("配图" in p for p in problems)


def test_uniform_short_headings_are_flagged():
    """四个字一排的小标题是模板味的典型信号，至少要提示。"""
    heading = "## 驱动问题\n## 评分分歧\n## 容量体量\n"
    _, notes = check_post(_md(heading=heading))
    assert any("四字" in n for n in notes)


# ── 命令行 ────────────────────────────────────────────────


def test_cli_exit_code_is_1_on_failure(tmp_path):
    target = tmp_path / "short.md"
    target.write_text("太短", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_post.py"), str(target)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1


def test_cli_exit_code_is_0_on_pass(tmp_path):
    target = tmp_path / "ok.md"
    target.write_text(_md(), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_post.py"), str(target)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_cli_requires_an_argument():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_post.py")],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2


def test_cli_missing_file_is_usage_error(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_post.py"), str(tmp_path / "nope.md")],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2


@pytest.mark.parametrize("body_len", [MIN_CHARS - 1, MIN_CHARS, MIN_CHARS + 1])
def test_boundary_around_min_chars(body_len):
    """边界要卡准：不够拦，够就放。

    注意小标题文字也算正文，所以拿 count_body_chars 结果判断，
    不能拿 body_len 直接比。
    """
    md = _md(body="字" * body_len)
    problems, _ = check_post(md)
    passed = not any(str(MIN_CHARS) in p for p in problems)
    assert passed is (count_body_chars(md) >= MIN_CHARS)


# ── 发布流程拦截 ──────────────────────────────────────────

import argparse

from xhh_agent.cli import cmd_post
from xhh_agent.config import load_config


def _args(md_path, *, allow_short: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        md=str(md_path),
        html=None,
        title="标题",
        tag=None,
        topic=None,
        html_out=None,
        yes=True,
        edit_link=None,
        allow_short=allow_short,
    )


async def test_publish_aborts_on_short_post(tmp_path, capsys):
    """硬规则要卡在发布流程里，不能只靠我自觉去跑脚本。"""
    source = tmp_path / "short.md"
    source.write_text("太短了，根本不够 1500 字。", encoding="utf-8")

    code = await cmd_post._run(load_config(), _args(source), draft=True)

    assert code == cmd_post.EXIT_USAGE
    err = capsys.readouterr().err
    assert str(MIN_CHARS) in err
    assert "--allow-short" in err


async def test_allow_short_bypasses_the_gate(tmp_path, monkeypatch):
    """确实要发短帖时能显式绕过，且要打警告。

    这条同时证明：拿到 --allow-short 后流程确实往前走（走到登录检查才停）。
    """
    from xhh_agent.protocol.errors import LoginExpired

    source = tmp_path / "short.md"
    source.write_text("太短了，根本不够 1500 字。", encoding="utf-8")

    def expired(_path):
        raise LoginExpired("测试：没有会话")

    monkeypatch.setattr(cmd_post, "SessionStore", expired)
    code = await cmd_post._run(
        load_config(), _args(source, allow_short=True), draft=True
    )

    assert code == cmd_post.EXIT_LOGIN_EXPIRED
