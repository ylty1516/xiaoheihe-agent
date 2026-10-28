# tests/test_signer.py
from xhh_agent.protocol.signer import create_signed_params


def test_returns_three_keys():
    p = create_signed_params("/bbs/app/user/message")
    assert set(p) == {"hkey", "_time", "nonce"}
    assert isinstance(p["_time"], int)
    assert p["_time"] > 1_700_000_000      # 不是毫秒，也不是 0


def test_nonce_is_uppercase_md5():
    p = create_signed_params("/bbs/app/user/message")
    assert len(p["nonce"]) == 32
    assert p["nonce"] == p["nonce"].upper()


def test_path_normalization_accepts_with_or_without_slashes():
    """上游对 path 做了补斜杠归一化，两种写法应产出同构结果"""
    a = create_signed_params("/bbs/app/user/message")
    b = create_signed_params("bbs/app/user/message")
    assert len(a["hkey"]) == len(b["hkey"])


def test_hkey_shape():
    p = create_signed_params("/bbs/app/comment/create")
    # 上游算法：hkey = _map_by_alphabet(md5[:5]) + str(sum % 100).zfill(2)，长度恒为 7
    assert len(p["hkey"]) == 7
    assert p["hkey"][-2:].isdigit()


def test_two_calls_differ():
    """nonce 带随机，连续两次不能相同，否则会被防重放拦"""
    a = create_signed_params("/x/y")
    b = create_signed_params("/x/y")
    assert a["nonce"] != b["nonce"] or a["hkey"] != b["hkey"]
