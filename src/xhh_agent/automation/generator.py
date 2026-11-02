"""AI 生成回复。

分三层，每层各管一件事：

1. ``build_prompt`` —— 把帖子语境、对方评论、语气规格拼成 prompt
2. ``validate_generated`` —— **生成后的闸门**。这一步比生成更重要：
   模型很容易写出「我上周也买了…」这种编造经历的句子，那比语气不像人严重得多
3. ``LlmReplyGenerator`` —— 串起来，不达标就重试一次，两次都不行就报错

校验不通过宁可不发。这是 C4（不编造第一人称经历）在代码里的落地。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from xhh_agent.protocol.models import InboxItem
from xhh_agent.content.persona import BASE_STYLE, FACT_GUARD, compile_persona, reference

logger = logging.getLogger(__name__)

#: 回复长度上限（规格 §5.7）
MAX_REPLY_LENGTH = 200

#: 编造第一人称经历。这是 C4 的红线，不是语气问题。
_FABRICATED_RE = re.compile(
    r"我(?:上周|上个月|昨天|前天|今天|之前|以前|去年|前年|小时候)"
    r"|我(?:买过|玩过|试过|去过|打过|用过|入手过)"
    r"|我(?:打|玩|用|肝)了\s*\d+",
)

_WRAP_QUOTES = "「」『』\"'“”‘’"


class GenerationError(RuntimeError):
    """生成失败，或生成内容没通过校验。"""


def _clean(text: str) -> str:
    cleaned = (text or "").strip()
    # 模型常加前缀
    for prefix in ("回复：", "回复:", "答：", "答:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    # 模型常把回复包在引号里
    if len(cleaned) >= 2 and cleaned[0] in _WRAP_QUOTES and cleaned[-1] in _WRAP_QUOTES:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def validate_generated(text: str) -> tuple[bool, str]:
    """校验生成内容。返回 (是否通过, 清洗后的文本或拒绝原因)。"""
    cleaned = _clean(text)
    if not cleaned:
        return False, "内容为空"
    if len(cleaned) > MAX_REPLY_LENGTH:
        return False, f"超过 {MAX_REPLY_LENGTH} 字（{len(cleaned)}）"

    fabricated = _FABRICATED_RE.search(cleaned)
    if fabricated:
        return False, f"疑似编造第一人称经历（C4）：{fabricated.group(0)}"

    return True, cleaned


def build_prompt(item: InboxItem, profile_text: str, persona_snapshot=None) -> str:
    """拼 prompt。语境（帖子标题 + 被回复的上文）必须带上，否则只能写空话。"""
    lines = [
        "你在运营一个小黑盒账号，现在要回复一条评论。",
        "",
        "## 账号语气规格",
        compile_persona(persona_snapshot, "comment")
        if persona_snapshot
        else (profile_text.strip() + "\n" + BASE_STYLE + "\n" + FACT_GUARD),
        "",
        "## 帖子标题",
        item.link_title or "（未知）",
    ]
    if item.replied_text:
        lines += ["", "## 被回复的上文", item.replied_text]
    lines += [
        "",
        "## 对方说",
        item.text,
        "",
        "## 要求",
        "- 默认简洁，通常15-40字；需要时完整回答，最多200字",
        "- **针对对方这句话的具体内容**回应，不要泛泛而谈",
        "- 语气参考账号规格和本次语境；不为固定口头禅删掉有用信息",
        "- **不编造第一人称经历**：不写「我上周…」「我买过…」这类 AI 无从知晓的事",
        "- 自然使用连接词，避免反复套话；不因出现某个词就刻意绕写",
        "- 只输出回复正文，不要解释，不要加引号",
    ]
    return "\n".join(lines)


class LlmReplyGenerator:
    """调模型生成回复，并过校验闸门。"""

    def __init__(
        self,
        *,
        client: Any,
        profile_text: str,
        model: str,
        max_attempts: int = 2,
        persona_snapshot=None,
    ) -> None:
        self._client = client
        self._profile_text = profile_text
        self._model = model
        self._max_attempts = max(1, max_attempts)
        self._persona_snapshot = persona_snapshot
        self.persona_reference = reference(persona_snapshot) if persona_snapshot else None

    async def generate(self, item: InboxItem) -> str:
        prompt = build_prompt(item, self._profile_text, self._persona_snapshot)
        last_reason = ""
        for attempt in range(self._max_attempts):
            raw = await self._client.complete(prompt=prompt, model=self._model)
            ok, value = validate_generated(raw)
            if ok:
                return value
            last_reason = value
            logger.warning("第 %d 次生成未通过校验：%s", attempt + 1, value)
        raise GenerationError(f"生成内容未通过校验：{last_reason}")


class OpenAICompatClient:
    """调 OpenAI 兼容的 /chat/completions。DeepSeek 也是这个协议。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def complete(self, *, prompt: str, model: str, max_tokens: int = 300) -> str:
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            "max_tokens": max_tokens,
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    raise GenerationError(f"模型接口返回 HTTP {response.status}：{body[:200]}")
        try:
            data = json.loads(body)
            return str(data["choices"][0]["message"]["content"] or "")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise GenerationError(f"模型响应结构异常：{type(exc).__name__}") from None
