# tests/test_config.py
import pytest
from xhh_agent.config import Config, load_config


def test_defaults_when_no_env(monkeypatch):
    monkeypatch.delenv("XHH_COOKIE", raising=False)
    cfg = load_config()
    assert cfg.draft_only is True          # 默认必须是草稿，安全侧
    assert cfg.reply_mode == "queue"
    assert cfg.poll_interval == 600
    assert cfg.max_message_age_hours == 6
    assert cfg.max_replies_per_hour == 5


def test_rate_limit_cannot_exceed_hard_cap(monkeypatch):
    """环境变量只能调低不能调高（规格 §5.3 / 全局约束）"""
    monkeypatch.setenv("XHH_MAX_REPLIES_PER_HOUR", "999")
    cfg = load_config()
    assert cfg.max_replies_per_hour == 5   # 硬上限，被夹回


def test_rate_limit_can_be_lowered(monkeypatch):
    monkeypatch.setenv("XHH_MAX_REPLIES_PER_HOUR", "2")
    assert load_config().max_replies_per_hour == 2


def test_invalid_int_raises_not_silently_defaults(monkeypatch):
    """配置写错要报错，不能静默用默认值跑起来"""
    monkeypatch.setenv("XHH_POLL_INTERVAL", "十分钟")
    with pytest.raises(ValueError, match="XHH_POLL_INTERVAL"):
        load_config()


def test_ai_disclosure_rejects_none(monkeypatch):
    """'被问也否认'在任何阶段都不接受（规格 §2 C1）"""
    monkeypatch.setenv("XHH_AI_DISCLOSURE", "none")
    with pytest.raises(ValueError, match="XHH_AI_DISCLOSURE"):
        load_config()


def test_config_is_immutable():
    cfg = load_config()
    with pytest.raises(Exception):
        cfg.reply_mode = "auto"


def test_config_has_no_cookie_field():
    """审查 I5/I6：Cookie 只有一个来源（.data/session.json）。
    Config 里留一份会把明文带进 repr/日志，且读它的代码并不存在。"""
    cfg = load_config()
    assert not hasattr(cfg, "cookie")
