// 影之刃零发帖值班：每 2 小时跑一次，发不发由 scripts/post_slot.py 决定。
// 定时任务通过 subagent schedule.create 挂载，名字「影之刃零发帖值班」。

const task = [
  "小黑盒发帖值班（只发《影之刃零》）。",
  "工作目录：F:/Grok_Workspace/01_Projects/xiaoheihe-agent",
  "",
  "第一步：完整读 docs/posting-duty.md、docs/style-ledger.md、voice/content-strategy.md、voice/profile.md，严格照做，不要临场发挥。",
  "",
  "铁律：",
  "1. 先跑 py -m xhh_agent.cli.main doctor；退出码 3 或不过 → 立刻停，报告会话失效。",
  "2. 跑 py scripts/post_slot.py check。只有返回 0 才允许 publish；返回 3 或 4 → 这轮只做逛热搜、看社区高赞帖、拆写法卡、写草稿，绝不发布，也不许改配置绕过。",
  "3. 全篇只写《影之刃零》，别的游戏一个字都不写。",
  "4. 正文 >=1000 字（目标 1500-2500），>=3 张配图，分区必须同时挂 PC游戏 和 影之刃零（发布命令加 --topic \"影之刃零\"，核对打印出来的分区行）。",
  "5. 发前跑 py scripts/check_post.py；再跑 py scripts/style_profile.py compare 新稿.md，退出码 1 就是结构和前两篇撞车，必须换写法重写，不许放行。",
  "6. 样式不许重样：每篇先从 docs/style-ledger.md 挑一张不同的写法卡当骨架，并且和最近两篇至少 3 项结构特征不同。",
  "7. 每读一篇社区帖子，按 docs/style-ledger.md 末尾那四个问题拆写法，记进 .data/ 临时笔记。",
  "8. 不许编造第一人称游玩经历；数据必须是查到的具体数字。",
  "9. 发布后核对：分区是 ['PC游戏','影之刃零']、正文无 .data/ 本地路径、图片已转存 imgheybox；然后 py scripts/post_slot.py record --link-id <id>。",
  "10. 任何一步失败（发布被拒、签名失败、分区解析失败）→ 停在草稿，不重试第二次，把原因写清楚。",
  "",
  "最后用中文简短汇报：这轮发没发、用了哪张写法卡、角度是什么、link_id、核对结果、下一轮该做什么。"
].join("\n");

const run = await runs.run("duty", { agent: "delegate", task });
return {
  runId: run.runId,
  status: run.status,
  output: run.output
};
