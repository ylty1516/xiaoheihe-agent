"""Bounded public API sources. Community popularity is not source verification."""

import re
from html import unescape

import aiohttp


async def fetch_sources(provider, key):
    if provider == "steam" and isinstance(key, str) and re.fullmatch(r"[0-9]{1,10}", key):
        url = f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={key}&count=8&maxlength=12000"
    elif (
        provider == "github"
        and isinstance(key, str)
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", key)
    ):
        url = f"https://api.github.com/repos/{key}/releases?per_page=8"
    else:
        raise ValueError("来源只支持 Steam AppID 或 GitHub owner/repo")
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20), trust_env=True
    ) as session:
        async with session.get(
            url, allow_redirects=False, headers={"User-Agent": "xhh-agent-research"}
        ) as response:
            if response.status != 200:
                raise ValueError(f"公开资料接口返回 HTTP {response.status}")
            raw = bytearray()
            async for chunk in response.content.iter_chunked(32768):
                raw.extend(chunk)
                if len(raw) > 2_000_000:
                    raise ValueError("公开资料响应过长")
            import json

            data = json.loads(raw)
    rows = data.get("appnews", {}).get("newsitems", []) if provider == "steam" else data
    if not isinstance(rows, list):
        raise ValueError("公开资料结构发生变化")
    result = []
    for row in rows[:8]:
        if not isinstance(row, dict) or row.get("draft"):
            continue
        text = row.get("contents" if provider == "steam" else "body") or ""
        text = unescape(re.sub(r"<[^>]*>", " ", str(text)))[:12000].strip()
        if text:
            result.append(
                {
                    "kind": "source",
                    "text": text,
                    "title": str(row.get("title") or row.get("name") or key)[:200],
                    "url": row.get("url" if provider == "steam" else "html_url", ""),
                    "published_at": row.get("date" if provider == "steam" else "published_at"),
                    "version": row.get("tag_name"),
                    "prerelease": row.get("prerelease"),
                    "provenance": provider + "_public_api",
                    "verification": "来源发布内容；未独立实测",
                    "provider": provider,
                    "key": key,
                }
            )
    return result
