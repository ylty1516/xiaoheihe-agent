"""小黑盒请求签名参数生成。

改编自 advent259141/astrbot_plugin_xiaoheihe_adapter (Apache-2.0)
上游 commit: 534b9479e9bebe4ef82d9ec959d0c11146c90078
修改说明：抽取为独立模块，去除对上游客户端类的依赖；算法逐字节保持一致。

**不要"优化"这些函数**。``_mix_columns`` 接收 6 个元素却只改写前 4 个的行为
是上游实现的一部分，改动会让校验和与服务器对不上。
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Iterable

_ALPHABET = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _mix_columns(values: list[int]) -> list[int]:
    values = list(values)

    def xtime(value: int) -> int:
        return ((value << 1) ^ 27) & 255 if value & 128 else value << 1

    def q(value: int) -> int:
        return xtime(value) ^ value

    def r(value: int) -> int:
        return q(xtime(value))

    def y(value: int) -> int:
        return r(q(xtime(value)))

    def g(value: int) -> int:
        return y(value) ^ r(value) ^ q(value)

    result = [0, 0, 0, 0]
    result[0] = g(values[0]) ^ y(values[1]) ^ r(values[2]) ^ q(values[3])
    result[1] = q(values[0]) ^ g(values[1]) ^ y(values[2]) ^ r(values[3])
    result[2] = r(values[0]) ^ q(values[1]) ^ g(values[2]) ^ y(values[3])
    result[3] = y(values[0]) ^ r(values[1]) ^ q(values[2]) ^ g(values[3])
    values[:4] = result
    return values


def _map_by_alphabet(value: str, alphabet: str, end: int) -> str:
    source = alphabet[:end]
    return "".join(source[ord(char) % len(source)] for char in value)


def _path_to_alphabet(value: str, alphabet: str) -> str:
    return "".join(alphabet[ord(char) % len(alphabet)] for char in value)


def _interleave(values: Iterable[str]) -> str:
    items = list(values)
    max_length = max((len(value) for value in items), default=0)
    result = []
    for i in range(max_length):
        for value in items:
            if i < len(value):
                result.append(value[i])
    return "".join(result)


def create_signed_params(path: str) -> dict[str, str | int]:
    """生成 ``hkey`` / ``_time`` / ``nonce`` 三个签名参数。

    ``_time`` 用 ``int(time.time())``（UTC 秒），不依赖本地时区——
    本地时钟偏移会让签名直接失效，``xhh doctor`` 会先检查这一点。
    """
    now = int(time.time())
    nonce = _md5(f"{now}{random.random()}").upper()
    normalized_path = "/" + "/".join(filter(None, path.split("/"))) + "/"
    alphabet = _ALPHABET
    seed = _interleave(
        [
            _map_by_alphabet(str(now + 1), alphabet, -2),
            _path_to_alphabet(normalized_path, alphabet),
            _path_to_alphabet(nonce, alphabet),
        ],
    )[:20]
    hash_value = _md5(seed)
    checksum_values = [ord(char) for char in hash_value[-6:]]
    checksum = str(sum(_mix_columns(checksum_values)) % 100).zfill(2)
    return {
        "hkey": f"{_map_by_alphabet(hash_value[:5], alphabet, -4)}{checksum}",
        "_time": now,
        "nonce": nonce,
    }
