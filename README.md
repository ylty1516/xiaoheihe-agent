# xiaoheihe-agent

> **v0.3.0** · 2026-10-28 · 小黑盒账号自动化（发帖 / 回评论 / 私信 / 逛帖学习）

让 AI agent 用**自己的**小黑盒账号发帖、回评论、回私信 —— 像一个真的在用的号，而不是自动回复机器人。

```
xhh publish --md 稿子.md --title "标题" --tag 1 --yes
```

---

## 截图

<!-- 把 App 里的帖子截图放到 docs/images/ 后替换这里 -->

| 发的帖子 | 终端命令 |
|---|---|
| ![帖子](docs/images/post.png) | ![终端](docs/images/cli.png) |

> 图还没放喵。放进去后把上面两行的路径对上就行。

---

## 能做什么

| 能力 | 命令 | 说明 |
|---|---|---|
| **发帖** | `publish` / `draft` | Markdown → 富文本文章，代码块和表格转图片上传图床 |
| **回评论** | `poll` → `queue` → `reply` | 只回自己帖子下的评论，每帖最多 5 次 |
| **私信** | `dm` / `dm --history` | 发消息、看历史 |
| **逛帖学习** | `study` | 每天挑高质量帖子，存成笔记供分析 |
| **删除** | `delete` | 删帖子或草稿（hex / 数字 ID 都支持） |

全是**纯 HTTP**，不需要 Playwright 或浏览器。签名在 Python 里算。

## 安装

```bash
git clone https://github.com/ylty1516/xiaoheihe-agent.git
cd xiaoheihe-agent
py -m venv .venv && .venv\Scripts\activate     # Windows
pip install -e ".[dev]"
```

macOS / Linux 用 `python3 -m venv .venv && source .venv/bin/activate`。

> **Windows 必须用 `py`**，`python` 是 Microsoft Store 的假 shim，执行后什么都不做也不报错。

## 使用

### 1. 登录一次

```bash
xhh login          # 弹出二维码图片，用小黑盒 App 扫一扫
xhh doctor         # 四项自检，全 OK 才能往下用
```

二维码内容是**给 App 扫的**，不是网页，粘进浏览器会跳到"该功能需要登录使用"。

### 2. 发帖

```bash
xhh draft   --md 稿子.md --title "标题" --tag 1 --html-out preview.html
xhh publish --md 稿子.md --title "标题" --tag 1 --yes
```

- `--tag` 是话题 ID，**必须是真实存在的**（`1` = PC游戏）。用错会报"错误的帖子类型"
- `draft` 只进草稿箱，`publish` 才公开
- `--html-out` 存一份 HTML 便于浏览器预览排版

### 3. 回评论

```bash
xhh poll --once                    # 扫自己帖子下的新评论，进队列
xhh queue list                     # 看队列
xhh queue show 3                   # 单条详情（含原帖标题、被回复的上文）
xhh reply --queue-id 3 --text "..." --send
```

`reply` 默认 dry-run，`--send` 才真发。

### 4. 逛帖学习

```bash
xhh study --count 2       # 挑 2 篇高质量帖子，存到 notes/study/
xhh study --list          # 看已记的笔记
```

笔记里有元数据、正文、7 个待分析问题、原始 JSON。**只读**，不点赞不评论。

## 三条硬约束（写在代码里）

1. **幂等优先** —— 同一条消息绝不回两次。宁可漏回，不可重发
2. **不批量** —— 频率上限写死在 `HARD_LIMITS`，环境变量只能调低不能调高
3. **不编造经历 / 不否认 AI** —— 不写"我上周打了 40 小时"这类 AI 无从知晓的事；被直接问到必须承认

「像真人」是**说话方式**的追求，不是**冒充真人经历**。这两条不能为了像而让步。

## 状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 登录 / 自检 / 只读拉消息 | ✅ 真机验收 |
| P1 | 发帖：排版转换、图床上传、草稿/发布 | ✅ 真机验收 |
| P2 | 回评论：幂等、闸门、三道决策门、队列 | ✅ 真机验收 |
| P3 | 私信：发送、历史 | ✅ 真机验收 |
| P3+ | 私信自动回复、AI 生成层 | 未做 |

## 版本

| 版本 | 日期 | 变更 |
|---|---|---|
| **0.3.0** | 2026-10-28 | 发帖（article/dynamic 双模式）、删除、逛帖学习、私信历史 |
| 0.2.0 | 2026-10-28 | 回评论闭环：幂等表、频率闸门、决策门、队列 |
| 0.1.0 | 2026-10-28 | P0 协议层：登录、自检、只读消息 |

## 风险

使用非公开接口，**违反平台用户协议的可能性很高**。可能被限流、禁言、封禁。

Cookie 等价于账号密码，只存在 `.data/session.json`（0600），不进日志、不进命令行、不入库。

如果这是你的主号且不能承受损失，只建议用 `draft` 能力，发布自己点。

## 文档

- 设计规格：[`docs/superpowers/specs/`](docs/superpowers/specs/)
- 实现计划：[`docs/superpowers/plans/`](docs/superpowers/plans/)
- agent 使用说明：[`skills/xiaoheihe-heybox/SKILL.md`](skills/xiaoheihe-heybox/SKILL.md)
