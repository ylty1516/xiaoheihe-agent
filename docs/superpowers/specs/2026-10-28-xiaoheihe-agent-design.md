# xiaoheihe-agent 设计规格

- 日期：2026-10-28
- 状态：**待审阅**（批准后才进入实现计划）
- 作者：Pi agent + 用户

---

## 1. 背景与目标

### 1.1 背景

用户希望 AI agent 通过其**本人的**小黑盒账号完成三件事：

1. 发帖（agent 写内容 → 排版 → 发布或存草稿）
2. 回复评论 / @提及
3. 回复私信

小黑盒没有覆盖社区发帖的开放 API。官方只提供 SDK（`docs.xiaoheihe.cn/hb_sdk`）和
机器人协议（`bot.xiaoheihe.cn/protocol/bot`），二者均不涉及社区发帖。因此本项目基于
Web 端非公开接口实现。

接口事实来源（均为读源码取证，非官方文档）：

| 能力 | 方法与路径 | 取证来源 |
|---|---|---|
| 读消息（@我 / 评论回复） | `GET /bbs/app/user/message` | better-XiaoHeiHe `doc/通用消息查询接口.md`；xhh_client.py `MESSAGE_API_PATH` |
| 回复评论 | `POST /bbs/app/comment/create`，字段 `link_id` `reply_id` `root_id` `text` `imgs` `is_cy` | better-XiaoHeiHe `src/content.js:12392`；xhh_client.py `submit_comment` |
| 发帖 | `POST /bbs/app/api/link/post` | xhh_client.py `LINK_POST_API_PATH` |
| 读私信会话 | `GET /chatroom/v2/msg/user` | xhh_client.py `fetch_direct_message_entries` |
| 发私信 | `POST /chatroom/v2/msg/user`，`msg_type=6` + `heybox_ack_id` | xhh_client.py `submit_direct_message` |
| 签名 | `hkey` / `_time` / `nonce` | xhh_client.py `create_signed_params` |

> 上一轮调研中"发私信走 `POST /chat/send_message/`"的说法是**错误**的（来自旧第三方客户端），
> 实际路径是 `POST /chatroom/v2/msg/user`。以源码为准。

### 1.2 目标

**项目方向（四个能力，后续主要投入）**：

1. **自动发帖** —— agent 写稿 → 小黑盒兼容 HTML → 存草稿或发布
2. **回评论** —— 别人评论你的帖子 / @你时生成并发出回复
3. **回私信** —— 一对一会话，回答别人的问题
4. **自己帖子的互动** —— 自家帖子下的评论回复与维护

共同质量目标是**“像真人一样”**：语气、句长、分寸感像一个人。
但这个追求有硬边界——它是**表达方式**的追求，不是**事实层面**的伪装：
语气像人，但不虚构第一人称经历（C4），被问 AI 就承认（C1）。
为“像人”而越过这两条，是这条路上最容易出的事。

**可验收的目标：**

- G1：agent 能把一份 Markdown 变成小黑盒正确渲染的帖子，并存成草稿
- G2：agent 能回复他人评论与 @提及（**包括自己帖子下的评论**），带幂等与频率保护
- G3：agent 能回复私信，默认走人工审核队列
- G4：进程崩溃、重启、重复启动，**绝不重复回复同一条消息**
- G5：所有自动化动作可审计（谁、何时、对谁、说了什么）
- G6：AI 产出与真人语气一致，且**不虚构真人的第一人称经历**

### 1.3 非目标

- 多账号 / 矩阵运营
- 批量私信、涨粉、营销
- 采集他人数据、爬取他人主页
- 对抗风控（不伪造设备指纹、不轮换 UA、不代理池）
- 图形界面的审核后台（P4 之前不做）

---

## 2. 硬约束

以下三条是项目的不可协商约束，任何实现细节与它们冲突时以此为准。

### C1 不否认 AI 身份

账号由**真人与 AI 混合运营**（AI 主要负责发帖）。处理原则：

- 被直接询问"这是 AI 发的吗"时，**必须承认**，不得否认、含糊或转移话题
- **不在每条内容上显式标注 AI 生成** —— 那会把账号变成 AI 号，违背混合运营的定位
- `XHH_AI_DISCLOSURE` 可取 `ask`（默认，被问才承认）或 `tag`（每条标注）
- `none`（即"被问也否认"）在任何阶段都不提供，代码层面不接受该值

理由：混合运营的正当性建立在"不欺骗"上 —— AI 帮忙产出，但有人问就承认。
这与"隐瞒 AI 参与"是两件不同的事。

### C2 不批量

所有通道都有硬频率上限。上限值写在代码常量中，环境变量**只能调低不能调高**。

理由：批量行为是这个项目唯一可能造成严重后果的地方。一次跑飞的循环可能在
十分钟内把账号送进风控。这种事故不该依赖"用户记得改配置"来避免。

### C3 幂等优先

同一消息 ID 绝不回复两次。**宁可漏回，不可重发。**

这条直接决定了幂等实现方式（见 5.1）：采用抢占式写入而非"先发后记"。

### C4 AI 不虚构第一人称经历

混合运营中最容易出事的不是"被认出是 AI"，而是 **AI 替真人编造经历**。

**禁止**生成：

- 第一人称具体经历（"我今天去店里试了…"、"上周我打了 40 小时…"）
- 虚构的消费、旅行、社交、身体状况
- 以真人身份做出的承诺、邀约、交易

**允许**生成：

- 观点、评测、分析、攻略、整理、推荐
- 以"我"表达偏好与判断（"我觉得这作战斗节奏偏慢"）—— 这是观点，不是经历

**判定标准**：这句话是否声称了一件**实际发生过、且 AI 无从知晓**的事？是则禁止。

这条无法靠频率闸门防护，只能靠提示词 + 生成后自检（见 §5.6）。

---

## 3. 架构

### 3.1 分层

```
┌──────────────────────────────────────────────┐
│  cli          xhh login / whoami / draft      │
│               / reply / poll / queue          │
└───────────────────┬──────────────────────────┘
                    │
┌───────────────────▼──────────────────────────┐
│  automation   轮询调度 · 过滤 · 幂等 · 闸门    │
│               回复生成 · 审核队列 · 审计       │
└──────┬────────────────────────────┬──────────┘
       │                            │
┌──────▼──────────┐        ┌────────▼─────────┐
│  content        │        │  store           │
│  Markdown→HTML  │        │  SQLite          │
│  图片预处理      │        │  幂等/队列/日志   │
│  长度校验        │        └──────────────────┘
└─────────────────┘
       │
┌──────▼───────────────────────────────────────┐
│  protocol   签名 · 登录 · HTTP · 接口封装     │
│             （唯一碰网络的模块）              │
└──────────────────────────────────────────────┘
```

依赖方向严格单向：`cli → automation → {content, store}`，`automation → protocol`。
`protocol` 不 import 任何上层模块。这样协议层可以单独替换（比如接口改版时）。

### 3.2 为什么不用 Playwright

`xiaoheihe-cli` 用 Playwright 拦签名请求，可行但代价大：常驻 Chromium（数百 MB 内存）、
agent 每次启动都要拉起浏览器、无头模式更容易被识别。

`xhh_client.py` 证明签名可以在纯 Python 里算出来，且支持纯 HTTP 扫码登录
（`request_qr_login` / `poll_qr_login`）。因此本项目的 protocol 层走纯 HTTP。

**代价**：签名逻辑一旦被平台改动就会全线失效，需要跟进修补。这是选型时明确接受的
风险，缓解手段见 §7.2。

### 3.3 为什么改造而不直接依赖

`xhh_client.py` 是 AstrBot 插件的内部模块，不是独立库：构造函数吃 AstrBot 的
`config: dict`，日志走插件 logger，错误类型也耦合插件。直接 import 会把 AstrBot
拖成硬依赖。

做法：把该文件的**协议实现部分**（签名、URL 构造、请求、响应归一化）抽进
`src/xhh_agent/protocol/`，保留 Apache-2.0 版权头并在文件顶部标注修改说明。
上游仓库 pin 到具体 commit，记录在 `vendor/UPSTREAM.md`。

---

## 4. 组件设计

### 4.1 protocol 层

```python
@dataclass(frozen=True)
class IncomingMessage:
    channel: Literal["comment", "mention", "dm"]
    message_id: str          # 全局唯一，幂等键组成
    sender_id: str
    sender_name: str
    text: str
    created_at: int          # 服务端时间戳，不用本地时间
    # comment/mention 专用
    link_id: str | None = None
    root_id: str | None = None
    reply_id: str | None = None
    link_title: str | None = None


class ProtocolClient:
    async def login_qr(self) -> LoginSession: ...
    async def whoami(self) -> Account: ...
    async def fetch_inbox(self, *, limit: int) -> list[IncomingMessage]: ...
    async def reply_comment(self, msg: IncomingMessage, text: str) -> SendResult: ...
    async def send_dm(self, msg: IncomingMessage, text: str) -> SendResult: ...
    async def submit_post(
        self, *, title: str, html: str, tag: int, draft: bool
    ) -> PublishResult: ...
```

约束：本层**不做业务判断**。不决定该不该回、回什么、频率超了要不要跳过。

### 4.2 content 层

```python
def markdown_to_heybox_html(md: str) -> str: ...
def validate_post(title: str, html: str) -> list[ValidationError]: ...
def validate_reply(text: str) -> list[ValidationError]: ...
```

纯函数，无网络、无 IO。全部可用快照测试覆盖。

小黑盒的 HTML 白名单窄，代码块和表格是最容易塌的地方。因此：
- 转换后用 `validate_post` 做结构自检（检查关键标签是否存活）
- P1 阶段所有发帖默认 `draft=true`，靠人眼确认渲染

### 4.3 automation 层

核心是 `PollRunner`，一个可被 cron 或常驻进程调用的幂等入口：

```python
class PollRunner:
    async def run_once(self) -> PollReport: ...
```

单次轮询的完整流程：

```
1. fetch_inbox()
2. 过滤：
   - 排除自己发的（sender_id == self.heybox_id）
   - 排除超出 XHH_MAX_MESSAGE_AGE_HOURS 的（用服务端 created_at）
   - 排除已在 processed 表中的
3. 按 channel 路由到对应处理器
4. 处理器生成回复草稿
5. 依 XHH_REPLY_MODE：
   - off   → 只写 processed，不生成
   - queue → 写 queue 表，等人放行
   - auto  → 过闸门 → 发送 → 写 sent_log
6. 返回 PollReport（供 agent 汇报）
```

**回复生成**不放在 automation 内部实现，而通过注入的 `ReplyGenerator` 协议：

```python
class ReplyGenerator(Protocol):
    async def generate(self, msg: IncomingMessage, ctx: ReplyContext) -> str: ...
```

理由：生成逻辑（用哪个模型、什么提示词）是 Pi 侧的职责，不是这个包的。包只负责
把它接进来、管住它。这样换成任何 LLM 或规则引擎都不用改代码。

### 4.4 store 层

SQLite，单文件（`XHH_DB_PATH`），WAL 模式。见 §5.2 schema。

---

## 5. 关键设计

### 5.1 幂等：抢占式写入

**问题**：如果按"先发送，成功后记录"的顺序，发送成功但写库前进程被 kill（或断电），
重启后会重发。反之如果失败也应该允许重试。

**方案**：发送前先抢占。

```
BEGIN IMMEDIATE;
INSERT INTO processed(channel, target_id, state, created_at)
  VALUES (?, ?, 'claimed', ?);
-- UNIQUE 冲突 → 说明别人/上次已经抢到 → 直接跳过，不发
COMMIT;
-- 抢到之后才发送
UPDATE processed SET state = 'sent' | 'failed', error = ?;
```

要点：
- 幂等键 `(channel, target_id)` 唯一约束，靠数据库而不是内存
- 抢占成功才发送，`claimed` 状态超过 10 分钟视为陈旧可清理（但不自动重发，
  只记 failed 等人看）
- **代价**：进程崩在"抢占成功但没发出"的窗口里，这条消息永久漏回。这符合 C3
  的"宁可漏回不可重发"

不可接受的替代方案：内存 set 去重（重启即失效）、时间戳比对（同一条消息可能被返回两次）。

### 5.2 Schema

```sql
CREATE TABLE processed (
    channel     TEXT NOT NULL,          -- comment | mention | dm | post
    target_id   TEXT NOT NULL,
    state       TEXT NOT NULL,          -- claimed | sent | failed | skipped
    sender_id   TEXT,
    error       TEXT,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER,
    PRIMARY KEY (channel, target_id)
);

CREATE TABLE queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    sender_name TEXT,
    incoming    TEXT NOT NULL,          -- 原始消息快照 JSON
    draft_reply TEXT NOT NULL,
    state       TEXT NOT NULL,          -- pending | approved | edited | rejected | sent
    created_at  INTEGER NOT NULL,
    UNIQUE (channel, target_id)
);

CREATE TABLE sent_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    text        TEXT NOT NULL,
    sent_at     INTEGER NOT NULL,
    ok          INTEGER NOT NULL
);

CREATE INDEX idx_sent_log_window ON sent_log(channel, sent_at);
```

`sent_log` 上的索引是频率闸门的查询依据。

### 5.3 频率闸门

```python
HARD_LIMITS = {
    "post_per_day":     3,
    "reply_per_hour":   5,
    "reply_per_day":   30,
    "dm_per_day":      10,
}
```

- 有效上限 = `min(HARD_LIMITS[...], 配置值)`
- 配置值大于硬上限时，**只警告，取硬上限**
- 闸门是 `send_*` 的唯一入口，不存在绕过路径（代码层面不给 `force=True`）

超限行为：停止处理，写入 `PollReport.blocked_reason`，本轮剩余消息不标记 processed
（下一轮还能处理），然后正常退出——不是抛异常，不是静默跳过。

### 5.4 时间窗

只处理 `now - XHH_MAX_MESSAGE_AGE_HOURS*h` 之后的消息。

- 时间基准用服务端 `created_at`，不用本地时钟（避免机器时区/时钟漂移出错）
- 超出窗口的消息写 `processed(state='skipped')`，这样不会每轮重复评估
- 理由：回复一周前的评论像诈尸，且这是"agent 开机即通杀历史未读"的典型事故

### 5.5 私信与评论的差异化处理

| 维度 | 评论 / @ | 私信 |
|---|---|---|
| 默认模式 | queue | queue |
| 日上限 | 30 | 10 |
| 公开性 | 公开，可辩解 | 一对一，更像骚扰 |
| 允许 auto 的用户 | 可开 | 需显式二次确认 |
| 内容禁止项 | 承诺/报价/医疗法律建议 | 同上 + 站外引导/联系方式 |

私信通道在 `XHH_REPLY_MODE=auto` 时需要额外的 `XHH_DM_AUTO_CONFIRM=yes`
双开关，避免全局开关误伤。

### 5.6 账号语气规格（Voice Profile）

混合运营最具体的风险是**人格分裂**：AI 发的帖和真人的互动看起来不像同一个人。
解法是给 AI 一份账号语气规格，让产出向真人靠拢。

`voice/profile.md`（真人可编辑的纯文本）：

- **基线**：句长、是否爱用短句、段落密度
- **用词**：常用词、禁用词、口头禅、方言与网络用语接受度
- **标点**：逗号串联还是句号断开、省略号习惯、感叹号频率
- **结构偏好**：爱不爱列点、爱不爱小标题、开头与收尾习惯
- **立场**：常驻观点、常玩的游戏类型、明确不评价的领域

应用规则：

1. 发帖与回复读**同一份** profile
2. profile 由真人维护，AI **不得自行改写**（防止风格漂移累积）
3. 生成后跑轻量自检：命中禁用词 → 重生成一次；仍命中 → 降级进 `queue` 交人处理
4. C4 的经历检查与 profile 的禁用词检查合并为一次 `validate_generated()`

### 5.7 回复决策（Should-Reply Gating）

回复前先判定"该不该回"，比"回什么"重要。逐条乱回是最快暴露机器特征的行为，
也最容易招致反感与举报。三道门按顺序执行：

**第一道：直接跳过**（记 `processed(state='skipped')`，不发、不入队）

- 纯表情 / 纯标点 / 无意义串（"顶"、"1"、"哈哈哈"、单个 emoji）
- 刷屏或广告（含联系方式、外链、导流）
- 挑衅、引战、地域或人身攻击
- 过去 30 分钟内已有人给出等价回复（避免重复刷屏）
- 涉及无法安全回答的领域（医疗、法律、投资、政治）

**第二道：强制进 queue**（禁止自动发出，不论 REPLY_MODE 为何）

- 负面反馈、投诉、质疑——这是人对人的事，必须真人处理
- 涉及金额、交易、合作邀约
- 任何要求做承诺的
- 检测到对方在问"你是不是 AI"→ 自动回复也必须遵守 C1 承认，
  且建议交人，因为这类对话的后续更难驾驭

**第三道：正常处理**

其余提问、讨论、求推荐 → 按 `XHH_REPLY_MODE` 走。

补充约束：

- 回复长度硬上限 200 字（评论区不是发帖区，长篇大论不像人说话）
- 回复前需读原帖上下文——这是真实需求（不知道在聊什么就回不了），
  不是为伪装而制造的虚假行为
- 同一用户连续消息合并处理，不逐条回

---

## 6. 与 Pi 的接入

选 **CLI 子命令**，不做 MCP server。理由：Pi 已有 bash，CLI 是最少活动部件的形式，
且便于人工调试和 cron 调用。

```bash
xhh login                      # 扫码登录，落 .data/session.json
xhh whoami                     # 验证会话有效
xhh doctor                     # 自检：签名、会话、接口连通
xhh draft --md post.md --title "标题" --tag 11   # 只存草稿
xhh publish --md post.md --title "标题" --yes    # 正式发布（需 --yes）
xhh poll --once                # 跑一轮
xhh queue list / show / approve <id> / reject <id>
```

配套一个 Pi skill（`~/.agents/skills/xiaoheihe/SKILL.md`），告诉 agent：
- 什么时候该用哪个命令
- 发帖前必须先 `draft` 给人看
- 回复一律走 queue，不得自行 `approve`
- 不得把 Cookie 打进命令行参数（会进 shell history）

---

## 7. 错误处理

### 7.1 分类

| 情况 | 判定 | 处理 |
|---|---|---|
| 会话失效 | `status != ok` 且含鉴权关键字 / HTTP 401 | 停轮询，标记 session 无效，要求重新登录 |
| 签名失效 | 签名参数被拒，但 Cookie 有效 | 同上，且记 `PROTOCOL_MAY_HAVE_CHANGED` 告警 |
| 网络错误 | 连接/超时 | 指数退避重试 3 次（1s/4s/16s），仍失败记 failed |
| 接口字段缺失 | 响应结构不符 schema | 降级为只读，告警，不发送任何内容 |
| 速率限制 | 平台返回限流码 | 停止本轮，把退避时间写入状态，下轮延后 |
| 内容被拒 | `comment/create` 返回非 ok | 记 failed + 原始响应，不重试（重试也是同样结果） |

### 7.2 签名失效的缓解

签名是全局单点。缓解措施：

1. `xhh doctor` 每次启动先自检，签名失效在"还没发任何东西"时就暴露
2. protocol 层把签名实现隔离在 `signer.py` 单文件，改版时只改一处
3. `vendor/UPSTREAM.md` 记录上游仓库和 commit，便于比对更新
4. 降级路径：若纯 HTTP 签名持续失效，protocol 层预留 `PlaywrightSigner` 备选实现
   （接口相同，走拦截签名请求的老路子）

---

## 8. 配置

见 `.env.example`。所有配置项通过 `XHH_` 前缀环境变量读取，代码里不硬编码。

配置分两类：
- **可自由调整**：轮询间隔、时间窗、日志级别、DB 路径
- **受硬约束限制**：频率上限（只能调低）、AI 声明模式（不能关）、draft_only（P1~P3 默认 true）

---

## 9. 测试策略

| 层 | 方式 | 关键用例 |
|---|---|---|
| protocol | 录制真实响应的脱敏 fixture + 快照 | 消息解析、私信解析、错误码归一化、签名稳定输出 |
| content | 纯函数快照 | 代码块、表格、嵌套列表、图片、超长标题、emoji |
| store | 真实 SQLite（tmp dir） | **并发抢占同一 target_id 只能成功一次** |
| automation | 注入 fake ProtocolClient + fake Generator | 时间窗边界、自消息过滤、闸门边界、queue/auto/off 三模式 |
| 端到端 | 本地 fake HTTP server | 完整一轮 poll，断言不重发 |

必测（不允许跳过）：
1. 同一 `(channel, target_id)` 连续两次 poll，第二次发送调用次数为 0
2. 进程在 `claimed` 后模拟崩溃，重启后不重发
3. 频率上限：第 N+1 次发送被拦，且不标记 processed
4. 自己的消息不被回复
5. §5.7 三道门各自的判定边界：纯表情不进队、负面反馈必进 queue（即使 auto 模式）、
   普通提问正常进入处理
6. `XHH_REPLY_MODE=auto` 下，§5.7 第二道项的发送调用次数仍为 0

---

## 10. 实施阶段

| 阶段 | 内容 | 风险 | 产出 |
|---|---|---|---|
| **P0** | 登录 + `whoami` + `doctor` + 只读拉取消息/私信 | 零（不发任何内容） | 能看见数据 |
| **P1** | `draft` 存草稿 | 低（不公开） | 能验证排版 |
| **P2** | 回评论，queue 模式 | 中 | 队列 + 放行 |
| **P3** | 回私信，queue 模式 | 中高 | 同上 |
| **P4** | auto 模式（需显式双开关） | 高 | 常驻轮询 |

每一阶段结束后需人工验证再进入下一阶段。P0 不通过不写 P1 的代码。

---

## 11. 决策记录（2026-10-28 全部确认）

| # | 项 | 结论 |
|---|---|---|
| 1 | 人设定位 | **AI 与真人混合运营，AI 主要负责发帖。** 不标注 AI，被问必承认 |
| 2 | 私信档位 | **默认 queue**（人工放行）。auto 需 `XHH_DM_AUTO_CONFIRM=yes` 双开关 |
| 3 | 账号数 | **单账号** |
| 4 | 审核界面 | **CLI**（`xhh queue list/show/approve/reject`） |
| 5 | 回复生成位置 | **Pi 侧注入**。包内只定义 `ReplyGenerator` 协议 |
| 6 | AI 是否承担回复 | **是（方案 A）**。评论与私信都由 AI 回复，但不含 §5.7 第二道的强制人工项 |

### 由方案 A 派生的额外要求

- automation 层全量实现：轮询、过滤、幂等、闸门、生成、发送
- **§5.7 回复决策成为必需件**，不是可选项——方案 A 下它是控制风险的主武器
- 首版实现默认 `XHH_REPLY_MODE=queue`，跑通并人工验收后再自行改 `auto`
- 回归测试必须覆盖 §5.7 三道门各自的判定边界

---

## 12. 风险

| 风险 | 可能性 | 影响 | 缓解 |
|---|---|---|---|
| 账号被限流/封禁 | 中高 | 高 | 频率闸门、默认 draft、默认 queue |
| 非公开接口改版 | 高（长期） | 中 | 签名隔离、doctor 自检、预留 Playwright 备选 |
| 回复内容不当 | 中 | 中（社交面） | queue 模式、长度上限、禁止项清单 |
| Cookie 泄露 | 低 | 极高 | 只在 `.data/`、`.gitignore` 严格、不进命令行参数 |
| 违反用户协议 | **确定** | 取决于平台裁量 | 已在 README 声明，用户自行选择 |

关于最后一条：本项目使用非公开接口，**违反平台用户协议的可能性很高**。这不是可以
靠设计消除的风险，只能由使用者评估并承担。本文档不为此提供任何规避手段。
