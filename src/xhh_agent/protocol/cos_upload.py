"""小黑盒图床（腾讯云 COS）上传。

为什么需要：发帖时若正文里是 ``data:image/png;base64,...`` 内嵌图，
服务端会回"图片链接不合法"——必须先传到图床拿 URL。

流程：info（拿 bucket/key） → token（拿临时凭证） → PUT（直传 COS） → callback（拿 URL）。

签名算法移植自 advent259141/astrbot_plugin_xiaoheihe_adapter (Apache-2.0)，
是腾讯云 COS 的 ``q-sign-algorithm=sha1``。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import quote, urlencode

from .errors import SchemaChanged, TransportError

INFO_PATH = "/bbs/app/api/qcloud/cos/upload/info/v2"
TOKEN_PATH = "/bbs/app/api/qcloud/cos/upload/token/v2"
CALLBACK_PATH = "/bbs/app/api/qcloud/cos/upload/callback/v2"
DEFAULT_REGION = "ap-shanghai"


def cos_quote(value: str) -> str:
    return quote(value, safe="/-_.~")


def _hmac_sha1(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha1).hexdigest()


def cos_authorization(
    *,
    secret_id: str,
    secret_key: str,
    method: str,
    path: str,
    headers: dict[str, str],
    start_time: int,
    end_time: int,
) -> str:
    """生成 COS 请求签名。纯函数，给定输入输出恒定。"""
    method_lower = method.lower()
    key_time = f"{start_time};{end_time}"
    header_items = {
        key.lower(): " ".join(str(value).strip().split())
        for key, value in headers.items()
        if str(value).strip()
    }
    sorted_header_keys = sorted(header_items)
    signed_headers = ";".join(sorted_header_keys)
    http_headers = "&".join(
        f"{quote(key, safe='-_.~')}={quote(header_items[key], safe='-_.~')}"
        for key in sorted_header_keys
    )
    http_string = "\n".join([method_lower, cos_quote(path), "", http_headers, ""])
    sign_key = _hmac_sha1(secret_key.encode("utf-8"), key_time)
    string_to_sign = "\n".join(
        ["sha1", key_time, hashlib.sha1(http_string.encode("utf-8")).hexdigest(), ""],
    )
    signature = _hmac_sha1(sign_key.encode("utf-8"), string_to_sign)
    return (
        "q-sign-algorithm=sha1&"
        f"q-ak={secret_id}&"
        f"q-sign-time={key_time}&"
        f"q-key-time={key_time}&"
        f"q-header-list={signed_headers}&"
        "q-url-param-list=&"
        f"q-signature={signature}"
    )


class CosUploader:
    """把一张图片传到小黑盒图床，返回可访问的 URL。"""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def upload(
        self,
        *,
        data: bytes,
        name: str,
        mimetype: str = "image/png",
        width: int = 0,
        height: int = 0,
    ) -> str:
        if not data:
            raise ValueError("图片数据为空")

        info = await self._info(name, mimetype, len(data), width, height)
        keys = info.get("keys") if isinstance(info.get("keys"), list) else []
        key = str(keys[0] if keys else info.get("key") or "")
        bucket = str(info.get("bucket") or "")
        region = str(info.get("region") or DEFAULT_REGION)
        if not key or not bucket:
            raise SchemaChanged("图片上传初始化响应缺少 bucket 或 key")

        token = await self._token(bucket, [key], mimetype)
        await self._client._put_cos_object(
            data=data,
            bucket=bucket,
            region=region,
            key=key,
            mimetype=mimetype,
            token=token,
        )
        return await self._callback([key])

    async def _info(
        self, name: str, mimetype: str, size: int, width: int, height: int
    ) -> dict[str, Any]:
        file_info = {
            "name": name,
            "mimetype": mimetype,
            "fsize": size,
            "width": width,
            "height": height,
            "duration": 0,
        }
        body = urlencode(
            {
                "file_infos": json.dumps(
                    [file_info], ensure_ascii=False, separators=(",", ":")
                ),
                "scope": "bbs",
                "need_cache": "0",
            },
        )
        data = await self._client._request_json(
            "POST",
            self._client.build_api_url(INFO_PATH, {"heybox_id": self._client.heybox_id}),
            data=body,
            headers=self._client._form_headers(),
        )
        if data.get("status") != "ok":
            raise TransportError(f"图片上传初始化失败：{data.get('msg') or 'unknown'}")
        return data.get("result") if isinstance(data.get("result"), dict) else {}

    async def _token(self, bucket: str, keys: list[str], mimetype: str) -> dict[str, Any]:
        body = urlencode(
            {
                "bucket": bucket,
                "keys": json.dumps(keys, ensure_ascii=False, separators=(",", ":")),
                "mimetypes": json.dumps([mimetype], ensure_ascii=False, separators=(",", ":")),
                "is_multipart_upload": "0",
            },
        )
        data = await self._client._request_json(
            "POST",
            self._client.build_api_url(TOKEN_PATH, {"heybox_id": self._client.heybox_id}),
            data=body,
            headers=self._client._form_headers(),
        )
        if data.get("status") != "ok":
            raise TransportError(f"图片上传授权失败：{data.get('msg') or 'unknown'}")
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        credentials = result.get("credentials") if isinstance(result.get("credentials"), dict) else {}
        if not all(
            str(credentials.get(k) or "")
            for k in ("tmpSecretId", "tmpSecretKey", "sessionToken")
        ):
            raise SchemaChanged("图片上传授权响应缺少临时凭证")
        return result

    async def _callback(self, keys: list[str]) -> str:
        body = urlencode(
            {"keys": json.dumps(keys, ensure_ascii=False, separators=(",", ":"))},
        )
        data = await self._client._request_json(
            "POST",
            self._client.build_api_url(
                CALLBACK_PATH, {"heybox_id": self._client.heybox_id, "is_finished": "true"}
            ),
            data=body,
            headers=self._client._form_headers(),
        )
        if data.get("status") != "ok":
            raise TransportError(f"图片上传回调失败：{data.get('msg') or 'unknown'}")
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        preview_urls = result.get("preview_urls") if isinstance(result.get("preview_urls"), list) else []
        thumbs = result.get("thumbs") if isinstance(result.get("thumbs"), list) else []
        url = str(preview_urls[0] if preview_urls else (thumbs[0] if thumbs else ""))
        if not url:
            raise SchemaChanged("图片上传回调响应缺少 preview_url，无法确认是否上传成功")
        return url
