# P0 协议基础层 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 `xhh` 命令能扫码登录、验证会话、自检接口连通性，并**只读**拉取未读消息（评论 / @ / 私信），全程不发送任何内容。

**架构：** 薄封装上游 `xhh_client.py` 的协议实现，抽出为独立 `protocol` 包；配置、异常、会话持久化各自独立文件。CLI 只做参数解析与输出，不含业务逻辑。

**技术栈：** Python 3.13（`py` 命令）、aiohttp、pytest + pytest-asyncio、SQLite（P0 未使用，P2 起用）

**规格：** `docs/superpowers/specs/2026-10-28-xiaoheihe-agent-design.md`（执行者两份都读）

## 全局约束

- Python `>=3.11`；Windows 下用 `py`，不要用 `python`（Microsoft Store 假 shim）
- **Cookie 等价于账号密码**：只允许落在 `.data/`，文件权限 0600；**不得**出现在命令行参数、日志、异常消息、stdout 中
- CLI 所有输出强制 UTF-8（`main.py` 已有 `_force_utf8_output()`，新命令复用）
- 时间基准一律用**服务端** `timestamp`，不用本地时钟做业务判断
- P0 阶段**不实现任何发送能力**，`protocol` 层不出现 `submit_*` / `reply_*` / `send_*` 方法
- 频率硬上限常量定义在 `automation/limits.py`，环境变量只能调低不能调高（P0 只建常量表，不启用）

## 审查重点（Review Focus）

| # | 输入 / 失败模式 | 正常人期待的行为 | 钉住它的测试所在任务 |
|---|---|---|---|
| 1 | Cookie 被写进日志或异常消息 | 日志里只出现 `heybox_id`，绝不出现 hkey/cookie 原值 | 任务 2、任务 4 |
| 2 | 本地时钟偏移 / 时区错误 | 签名用 `int(time.time())` 不依赖本地时区；`doctor` 明确报告时钟偏差 | 任务 3、任务 7 |
| 3 | 接口返回结构变化（字段缺失、类型变了） | 抛 `SchemaChanged` 而不是返回空列表——空列表会让人以为"没人找我" | 任务 6 |
| 4 | 登录态过期 | 抛 `LoginExpired` 并以退出码 3 结束，提示重新登录，而不是静默返回空 | 任务 4、任务 6 |
| 5 | `message_id` 缺失时上游兜底为 `f"{link_id}:{reply_id}"` | 同一 reply 下多条消息（如"赞"和"回复"）会撞键 → 幂等误判。P0 只读，但必须在解析层保留原始 `message_type` 供 P2 区分 | 任务 6 |

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/xhh_agent/config.py` | 读取 `XHH_*` 环境变量，产出不可变 `Config` |
| `src/xhh_agent/protocol/errors.py` | 异常层级：`XhhError` → `LoginExpired` / `SchemaChanged` / `TransportError` / `RateLimited` |
| `src/xhh_agent/protocol/signer.py` | `create_signed_params(path)` 及其字母表映射辅助函数 |
| `src/xhh_agent/protocol/session.py` | Cookie 读写 `.data/session.json`（0600），`Session` dataclass |
| `src/xhh_agent/protocol/models.py` | `Account` / `InboxItem` / `InboxPage` |
| `src/xhh_agent/protocol/client.py` | `ProtocolClient`：HTTP 请求、扫码登录、`whoami`、`fetch_inbox` |
| `src/xhh_agent/cli/cmd_login.py` | `xhh login` |
| `src/xhh_agent/cli/cmd_whoami.py` | `xhh whoami` |
| `src/xhh_agent/cli/cmd_doctor.py` | `xhh doctor` |
| `src/xhh_agent/cli/cmd_inbox.py` | `xhh inbox` |
| `src/xhh_agent/cli/output.py` | JSON 输出封装 + 退出码约定 |
| `tests/fixtures/*.json` | 脱敏后的真实响应样本 |

**退出码约定**：`0` 成功 / `1` 一般错误 / `2` 参数错误 / `3` 登录态失效 / `4` 接口结构变化。

---

### 任务 1：配置层

**文件：**
- 创建：`src/xhh_agent/config.py`
- 测试：`tests/test_config.py`

- [ ] **步骤 1：编写失败的测试**

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`py -m pytest tests/test_config.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'xhh_agent.config'`

- [ ] **步骤 3：实现 `src/xhh_agent/config.py`**

`HARD_LIMITS` 字典逐字照抄规格 §5.3：`post_per_day=3, reply_per_hour=5, reply_per_day=30, dm_per_day=10`。

`Config` 用 `@dataclass(frozen=True)`。`load_config()` 读环境变量，int 型解析失败时抛 `ValueError` 并带上变量名；频率项用 `min(env_value, HARD_LIMITS[key])` 夹取，被夹取时 `logging.warning` 一次（只报变量名，不报值以外的敏感信息）。

`reply_mode` 只接受 `off|queue|auto`；`ai_disclosure` 只接受 `ask|tag`。

- [ ] **步骤 4：运行测试验证通过**

运行：`py -m pytest tests/test_config.py -v`
预期：6 passed

- [ ] **步骤 5：Commit**

```bash
git add src/xhh_agent/config.py tests/test_config.py
git commit -m "feat(config): 环境变量配置加载与频率硬上限夹取"
```

---

### 任务 2：异常层级与会话持久化

**文件：**
- 创建：`src/xhh_agent/protocol/errors.py`、`src/xhh_agent/protocol/session.py`
- 测试：`tests/test_session.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_session.py
import json, os, stat, sys
import pytest
from xhh_agent.protocol.session import Session, SessionStore
from xhh_agent.protocol.errors import LoginExpired


def test_save_and_load_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "session.json")
    store.save(Session(cookie="a=b; c=d", heybox_id="123", device_id="dev"))
    loaded = store.load()
    assert loaded.heybox_id == "123"
    assert loaded.cookie == "a=b; c=d"


def test_file_mode_is_owner_only(tmp_path):
    """Cookie 等价于密码，文件不能被组/其他用户读（审查重点 #1）"""
    p = tmp_path / "session.json"
    SessionStore(p).save(Session(cookie="a=b", heybox_id="1", device_id="d"))
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_load_missing_file_raises_login_expired(tmp_path):
    with pytest.raises(LoginExpired):
        SessionStore(tmp_path / "nope.json").load()


def test_repr_never_leaks_cookie(tmp_path):
    """即便被打进日志也不能泄露（审查重点 #1）"""
    s = Session(cookie="SECRET_COOKIE_VALUE", heybox_id="1", device_id="d")
    assert "SECRET_COOKIE_VALUE" not in repr(s)
    assert "1" in repr(s)          # heybox_id 可见，便于排查


def test_corrupt_json_raises_actionable_error(tmp_path):
    p = tmp_path / "session.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(LoginExpired, match="login"):
        SessionStore(p).load()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`py -m pytest tests/test_session.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'xhh_agent.protocol.session'`

- [ ] **步骤 3：实现**

`errors.py`：`XhhError(Exception)` 基类，子类 `LoginExpired` / `SchemaChanged` / `TransportError` / `RateLimited`。每个异常消息里**只允许**出现接口路径和状态码，不允许出现完整 URL 的 query 部分（那里有 hkey）。

`session.py`：`Session` 用 `@dataclass(frozen=True)`，自定义 `__repr__` 只输出 `heybox_id` 与 `device_id`（**不含 cookie/hkey**）。`SessionStore.save()` 写文件后 `os.chmod(path, 0o600)`（Windows 上 `chmod` 只影响只读位，仍需调用以保持一致行为）；`load()` 在文件缺失或 JSON 损坏时抛 `LoginExpired`，消息文案含 `run 'xhh login'`。

`device_id` 取值顺序：Cookie 中的 `device_id` → 否则用上游常量默认值 `02f61cdb0c14c026f9e6865d7744b86e`。不要随机生成——每换一次 device_id 就相当于新设备，徒增风控信号。

- [ ] **步骤 4：运行测试验证通过**

运行：`py -m pytest tests/test_session.py -v`
预期：5 passed（Windows 下 `test_file_mode_is_owner_only` 自动跳过）

- [ ] **步骤 5：Commit**

```bash
git add src/xhh_agent/protocol/errors.py src/xhh_agent/protocol/session.py tests/test_session.py
git commit -m "feat(protocol): 异常层级与 0600 权限的会话持久化"
```

---

### 任务 3：签名实现

**文件：**
- 创建：`src/xhh_agent/protocol/signer.py`
- 修改：`vendor/UPSTREAM.md`（补 commit pin）
- 测试：`tests/test_signer.py`

- [ ] **步骤 1：拉取上游并 pin commit**

```bash
mkdir -p vendor/upstream && cd vendor/upstream
git clone --depth 1 https://github.com/advent259141/astrbot_plugin_xiaoheihe_adapter .
git rev-parse HEAD   # 把 hash 写进 vendor/UPSTREAM.md
```

- [ ] **步骤 2：编写失败的测试**

```python
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
```

> 注：`hkey` 的长度与末两位数字已在实现前按上游算法确定，不需迭代调整。

- [ ] **步骤 3：运行测试验证失败**

运行：`py -m pytest tests/test_signer.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'xhh_agent.protocol.signer'`

- [ ] **步骤 4：实现 `signer.py`**

从 `vendor/upstream/xhh_client.py` 移植以下函数（保持算法逐字节一致，不要"优化"）：
`_md5`、`_map_by_alphabet`、`_path_to_alphabet`、`_interleave`、`_mix_columns`、`create_signed_params`。

文件顶部加 Apache-2.0 声明：

```python
# 改编自 advent259141/astrbot_plugin_xiaoheihe_adapter (Apache-2.0)
# 修改：抽取为独立模块，去除上游依赖
# 上游 commit: <步骤 1 得到的 hash>
```

- [ ] **步骤 5：运行测试验证通过**

运行：`py -m pytest tests/test_signer.py -v`
预期：5 passed

- [ ] **步骤 6：Commit**

```bash
git add src/xhh_agent/protocol/signer.py tests/test_signer.py vendor/UPSTREAM.md
git commit -m "feat(protocol): 移植签名实现并标注上游出处"
```

---

### 任务 4：ProtocolClient 骨架与 whoami

**文件：**
- 创建：`src/xhh_agent/protocol/client.py`、`src/xhh_agent/protocol/models.py`
- 测试：`tests/test_client_whoami.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_client_whoami.py
import pytest
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, SchemaChanged


async def test_whoami_parses_account(fake_client):
    acct = await fake_client.whoami()
    assert acct.heybox_id == "83709585"
    assert acct.username == "测试用户"


async def test_whoami_login_expired(fake_401_client):
    with pytest.raises(LoginExpired):
        await fake_401_client.whoami()


async def test_whoami_missing_fields_raises_schema_changed(fake_empty_result_client):
    """返回空 result 时不能当"匿名用户"，必须报结构变化（审查重点 #3）"""
    with pytest.raises(SchemaChanged):
        await fake_empty_result_client.whoami()


def test_url_building_never_logged_with_hkey(fake_client, caplog):
    """任何日志都不能含 hkey 值（审查重点 #1）"""
    fake_client.build_api_url("/bbs/app/user/message", {"heybox_id": "1"})
    assert "hkey=" not in caplog.text
```

`fake_client` / `fake_401_client` / `fake_empty_result_client` 用 `conftest.py` 的 fixture 构造：注入一个假的 aiohttp session（或用 `aioresponses`），返回 `tests/fixtures/whoami_ok.json` 等。

- [ ] **步骤 2：运行测试验证失败**

运行：`py -m pytest tests/test_client_whoami.py -v`
预期：FAIL（client 模块不存在）

- [ ] **步骤 3：实现**

`models.py`：`Account(heybox_id, username, level)`、`InboxItem(...)`、`InboxPage(items, has_more)` 均为 frozen dataclass。

`client.py`：`ProtocolClient(session: Session, config: Config)`。
- `build_api_url(path, params)` — **同步方法**（不 await）。拼接 `https://api.xiaoheihe.cn`，合并 `create_signed_params(path)`，返回 str。**该方法内部不得打日志输出 url 的 query**。
- `_request_json(method, url, **kw)` — 移植上游逻辑，把上游的 `XiaoHeiHeLoginExpired` 映射为 `LoginExpired`，`XiaoHeiHeClientError` 映射为 `TransportError`。
- `whoami()` — GET 用户信息接口，`result` 为空或缺 `heybox_id` 时抛 `SchemaChanged`。
- `close()` — 释放 aiohttp session，供 `async with` 使用。

- [ ] **步骤 4：运行测试验证通过**

运行：`py -m pytest tests/test_client_whoami.py -v`
预期：4 passed

- [ ] **步骤 5：Commit**

```bash
git add src/xhh_agent/protocol/client.py src/xhh_agent/protocol/models.py tests/test_client_whoami.py tests/conftest.py tests/fixtures/
git commit -m "feat(protocol): ProtocolClient 骨架与 whoami"
```

---

### 任务 5：扫码登录

**文件：**
- 修改：`src/xhh_agent/protocol/client.py`
- 创建：`src/xhh_agent/cli/cmd_login.py`
- 测试：`tests/test_login.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_login.py
async def test_request_qr_returns_url_and_id(fake_qr_client):
    qr = await fake_qr_client.request_qr_login()
    assert qr.qr_url.startswith("https://")
    assert qr.qr
    assert qr.expire > 0


async def test_poll_returns_pending_then_ok(fake_qr_client, monkeypatch):
    """未扫码返回 pending，扫码确认后返回会话"""
    assert (await fake_qr_client.poll_qr_login("qid")).status == "pending"
    monkeypatch.setattr(fake_qr_client, "_qr_state", "ok")
    result = await fake_qr_client.poll_qr_login("qid")
    assert result.status == "ok"
    assert result.session.heybox_id


async def test_login_saves_session_without_logging_cookie(fake_qr_client, tmp_path, caplog):
    store = SessionStore(tmp_path / "s.json")
    await fake_qr_client.login_and_save(store)
    assert store.load().cookie
    assert "hkey" not in caplog.text.lower()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`py -m pytest tests/test_login.py -v`
预期：FAIL

- [ ] **步骤 3：实现**

`models.py` 新增两个类型（供 `login` 使用）：`QrTicket(qr, qr_url, expire)`、`QrPollResult(status, session=None, message="")`。

`ProtocolClient.request_qr_login()` / `poll_qr_login(qr)` — 移植上游（`/account/get_qrcode_url/` 与 `/account/qr_state/`，注意这两个走 `build_login_url`，**不带签名参数**）。

`login_and_save(store)` — 轮询直到 `ok` 或超时（`expire` 秒），从 `Set-Cookie` 收集 cookie 串；`heybox_id` 从 cookie 的 `user_heybox_id` 字段取，取不到则登录后调一次 `whoami()` 补全。调 `store.save()`。

`cmd_login.py` — 打印二维码 URL（终端不支持渲染图片，只输出 URL 供扫码），轮询期间每 3 秒打一个点。**不得打印 cookie 内容**。

`main.py` 接线：`login` 命令走 `asyncio.run`。

- [ ] **步骤 4：运行测试验证通过**

运行：`py -m pytest tests/test_login.py -v`
预期：3 passed

- [ ] **步骤 5：Commit**

```bash
git add src/xhh_agent/protocol/client.py src/xhh_agent/cli/cmd_login.py tests/test_login.py
git commit -m "feat: 纯 HTTP 扫码登录，会话落盘"
```

---

### 任务 6：只读拉取 inbox

**文件：**
- 修改：`src/xhh_agent/protocol/client.py`、`src/xhh_agent/protocol/models.py`
- 创建：`src/xhh_agent/cli/cmd_inbox.py`
- 测试：`tests/test_inbox.py`、`tests/fixtures/inbox_*.json`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_inbox.py
async def test_parses_comment_mention_and_dm(fake_inbox_client):
    page = await fake_inbox_client.fetch_inbox(limit=20)
    channels = {i.channel for i in page.items}
    assert channels == {"comment", "mention", "dm"}
    assert all(i.message_id for i in page.items)
    assert all(i.timestamp > 0 for i in page.items)


async def test_preserves_raw_message_type(fake_inbox_client):
    """审查重点 #5：message_id 可能被兜底成 link_id:reply_id，
    同一 reply 下的'赞'和'回复'会撞键。必须保留 message_type 供 P2 区分。"""
    page = await fake_inbox_client.fetch_inbox()
    assert all(i.raw_message_type for i in page.items)


async def test_filters_out_own_messages(fake_inbox_client):
    page = await fake_inbox_client.fetch_inbox()
    assert all(i.sender_id != fake_inbox_client.heybox_id for i in page.items)


async def test_schema_change_raises_not_empty(fake_broken_schema_client):
    """字段改名时必须报错，不能静默返回空列表（审查重点 #3）"""
    with pytest.raises(SchemaChanged):
        await fake_broken_schema_client.fetch_inbox()


async def test_skips_items_without_reply_target(fake_inbox_client):
    """没有 link_id/reply_id 的消息无法回复，应跳过而不是崩溃"""
    page = await fake_inbox_client.fetch_inbox()
    assert all(i.link_id for i in page.items if i.channel != "dm")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`py -m pytest tests/test_inbox.py -v`
预期：FAIL

- [ ] **步骤 3：实现**

`fetch_inbox(limit)` 串行调三次上游等价请求：
- 评论：`/bbs/app/user/message`，`message_type=""`，过滤 `message_type ∈ {"1","2"}`
- @提及：同接口 `message_type="16"`
- 私信：同接口 `list_type="2"`，`entry=message`

统一归一化为 `InboxItem(channel, message_id, sender_id, sender_name, text, timestamp, link_id, reply_id, root_id, raw_message_type)`。

关键：`result.messages` 键不存在时抛 `SchemaChanged`（**不是**返回空列表）。
`signer` 已保证 `_time` 用 `int(time.time())`；时间戳解析统一走 `int()` 并对非数字抛 `SchemaChanged`。

`cmd_inbox.py` — 输出 `{"ok": true, "count": N, "items": [...]}`，`--format json|table`，`table` 走固定列宽。

- [ ] **步骤 4：运行测试验证通过**

运行：`py -m pytest tests/test_inbox.py -v`
预期：5 passed

- [ ] **步骤 5：Commit**

```bash
git add src/xhh_agent/protocol/ src/xhh_agent/cli/cmd_inbox.py tests/test_inbox.py tests/fixtures/inbox_*.json
git commit -m "feat: 只读拉取评论/@/私信三类消息"
```

- [ ] **步骤 6：真机验证（需要用户配合）**

运行：`xhh login` → 手机扫码 → `xhh inbox`
预期：终端输出你真实的未读消息 JSON。**这一步是 P0 的唯一人工验收点。**

---

### 任务 7：doctor 自检

**文件：**
- 创建：`src/xhh_agent/cli/cmd_doctor.py`
- 测试：`tests/test_doctor.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_doctor.py
async def test_doctor_reports_clock_skew(fake_client, monkeypatch):
    """审查重点 #2：本地时钟偏差会让签名直接失效，
    doctor 必须在发任何内容前暴露它"""
    monkeypatch.setattr(fake_client, "server_time", lambda: int(time.time()) - 300)
    report = await run_checks(fake_client)
    assert any(c.name == "clock" and not c.ok for c in report.checks)


async def test_doctor_checks_in_order_and_short_circuits(fake_expired_client):
    report = await run_checks(fake_expired_client)
    names = [c.name for c in report.checks]
    assert names.index("session") < names.index("signature") < names.index("inbox")
    assert names[-1] == "inbox" or not report.checks[-1].ok


async def test_doctor_exit_code_is_3_on_expired_session(fake_expired_client):
    assert await doctor_main(fake_expired_client) == 3
```

- [ ] **步骤 2：运行测试验证失败**

运行：`py -m pytest tests/test_doctor.py -v`
预期：FAIL

- [ ] **步骤 3：实现**

`run_checks(client)` 依次检查并在首个失败处短路：
1. `session` — 从 `SessionStore` 加载，缺失即失败
2. `clock` — 从任意接口响应头或 `/account/...` 拿服务端时间，与本机 `time.time()` 比较，偏差 > 120 秒判失败
3. `signature` — 发一次只读请求（`message_type=""&limit=1`），验证签名被接受
4. `inbox` — 完整拉一次，验证三类通道都能解析

`cmd_doctor.py` 输出表格：`check / ok / detail`，退出码 0 或 3。

- [ ] **步骤 4：运行测试验证通过**

运行：`py -m pytest tests/test_doctor.py -v`
预期：3 passed

- [ ] **步骤 5：Commit**

```bash
git add src/xhh_agent/cli/cmd_doctor.py tests/test_doctor.py
git commit -m "feat: doctor 自检（会话/时钟/签名/收件箱）"
```

---

### 任务 8：CLI 接线与端到端冒烟

**文件：**
- 修改：`src/xhh_agent/cli/main.py`
- 测试：`tests/test_cli_smoke.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_cli_smoke.py
def test_all_p0_commands_are_wired(capsys):
    for cmd in ("login", "whoami", "doctor", "inbox"):
        with pytest.raises(SystemExit) as e:
            main([cmd, "--help"])
        assert e.value.code == 0


def test_unimplemented_command_returns_2_not_crash():
    """P1+ 命令应明确提示未实现，而不是 AttributeError"""
    assert main(["draft", "--md", "x.md"]) == 2


def test_output_is_utf8_even_on_gbk_console():
    assert sys.stdout.encoding.lower().replace("-", "") in ("utf8", "utf-8")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`py -m pytest tests/test_cli_smoke.py -v`
预期：FAIL（子命令未接线）

- [ ] **步骤 3：实现**

`main.py` 把 `login/whoami/doctor/inbox` 分派到各自 `cmd_*.py` 的 `main(args, cfg)`。保留现有 `_STAGES` 表，未实现命令仍返回 2。

- [ ] **步骤 4：运行全部测试**

运行：`py -m pytest -v`
预期：全部通过（约 30 个用例）

- [ ] **步骤 5：Commit**

```bash
git add src/xhh_agent/cli/main.py tests/test_cli_smoke.py
git commit -m "feat(cli): 接通 P0 四个命令"
```

---

## P0 完成标准

- [ ] `py -m pytest` 全绿
- [ ] `xhh login` 能扫码成功并落盘 `.data/session.json`（权限 0600 / Windows ACL 等效）
- [ ] `xhh doctor` 四项检查全 ok
- [ ] `xhh inbox` 能列出真实未读消息
- [ ] 全仓库 grep 不到任何 cookie 明文（`git grep -i "hkey=\|cookie="` 只应命中文档说明）
- [ ] `protocol/` 下不存在 `send` / `submit` / `reply` 开头的发送方法

## 明确不在 P0 范围

发帖、排版转换、回复生成、幂等表、频率闸门、轮询调度 —— 全部属于 P1~P3，本计划不涉及。
