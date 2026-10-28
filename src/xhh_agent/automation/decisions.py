"""回复决策三道门（规格 §5.7）。

逐条乱回是最快暴露机器特征的行为，也最容易招人烦。所以在"回什么"之前
先判定"该不该回"，按顺序过三道门：

1. **直接跳过** —— 纯表情、无意义、广告、引战、敏感领域、太旧
2. **强制人工** —— 投诉、交易、要求承诺、被问是否 AI。**即使 auto 模式也不自动发**
3. **正常处理** —— 其余按配置的 reply_mode 走

所有判定都偏保守：拿不准就往 queue 送，而不是自动发。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from xhh_agent.protocol.models import InboxItem

#: 去掉这些标记后剩余内容太少，就认为没有实际内容
_EMOJI_MARK_RE = re.compile(r"\[[a-zA-Z0-9_]+_[^\]]*\]")
_PUNCT_ONLY_RE = re.compile(r"^[\s\W_]*$", re.UNICODE)

_CHEAP_WORDS = {"顶", "1", "11", "111", "dd", "哈哈", "哈哈哈", "呵呵", "嗯", "哦", "好的", "在"}

_CONTACT_RE = re.compile(
    r"(微信|威信|vx|v信|wx|qq|扣扣|加我|私我|私聊加|联系方式|扫码)",
    re.IGNORECASE,
)
_INSULT_RE = re.compile(
    r"(傻逼|煞笔|蠢货|滚|废物|垃圾人|你妈|妈的|去死|智障|脑残)",
    re.IGNORECASE,
)
_SENSITIVE_RE = re.compile(
    r"(高血压|糖尿病|吃什么药|处方|判几年|起诉|律师函|投资建议|all\s*in|梭哈|稳赚|"
    r"领导|政府|政治|选举)",
    re.IGNORECASE,
)

_HARD_RE = re.compile(
    r"(退款|退货|欺骗|骗人|骗子|举报|投诉|赔偿|维权|假货|"
    r"多少钱|报价|交易|付款|转账|定金|"
    r"保证|承诺|发誓|一定|必须答应|"
    r"你是\s*(ai|机器人|人工智能)|是不是\s*(ai|机器人)|"
    r"自动回复|脚本|挂机)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DecideContext:
    now: int
    max_age_hours: int = 6


@dataclass(frozen=True)
class Decision:
    action: str          # reply | queue | skip
    reason: str
    #: 强制人工：即使 auto 模式也不得自动发出
    is_hard: bool = False


def _normalize(text: str) -> str:
    return _EMOJI_MARK_RE.sub("", text or "").strip()


def decide(item: InboxItem, ctx: DecideContext) -> Decision:
    text = item.text or ""
    bare = _normalize(text)

    # ── 第一道：直接跳过 ──────────────────────────────
    if not bare or _PUNCT_ONLY_RE.match(bare):
        return Decision("skip", "只有表情或标点，没有实际内容")

    if len(bare) <= 3 and bare.lower() in _CHEAP_WORDS:
        return Decision("skip", "无意义短语")

    if _CONTACT_RE.search(text):
        return Decision("skip", "疑似导流/联系方式")

    if _INSULT_RE.search(text):
        return Decision("skip", "含攻击性内容")

    if _SENSITIVE_RE.search(text):
        return Decision("skip", "涉及无法安全回答的领域")

    age_seconds = max(0, ctx.now - int(item.timestamp or 0))
    if age_seconds > ctx.max_age_hours * 3600:
        return Decision("skip", f"超过 {ctx.max_age_hours} 小时，不追旧评论")

    # ── 第二道：强制人工 ──────────────────────────────
    if _HARD_RE.search(text):
        return Decision("queue", "投诉/交易/承诺/质疑自动化 —— 必须人处理", is_hard=True)

    # ── 第三道：正常处理 ──────────────────────────────
    return Decision("reply", "普通互动")
