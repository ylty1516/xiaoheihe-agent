// 影之刃零发帖值班：每 2 小时跑一次，发不发由 scripts/post_slot.py 决定。
// 定时任务通过 subagent schedule.create 挂载，名字「影之刃零发帖值班」。
//
// 两个降级点（都是踩坑之后加的）：
// 1. 模型钉死，不吃全局 defaultModel——settings.json 里的 yunyun4/* 早已失效。
// 2. 模型链：主仓 503 时换下一个 provider，别让一轮整个作废。
//    重试是安全的：新一轮自己会跑 post_slot，刚发过就只存草稿，不会重复发。

const task = [
  "小黑盒发帖值班（只发《影之刃零》）。",
  "工作目录：F:/Grok_Workspace/01_Projects/xiaoheihe-agent",
  "",
  "第一步：完整读 docs/editorial-workflow.md、docs/posting-duty.md、voice/profile.md。文章结构、篇幅、连接词以 editorial-workflow 为准，profile 的短回复偏好不覆盖文章规则。",
  "",
  "铁律：",
  "1. 先跑 py -m xhh_agent.cli.main doctor；退出码 3 或不过 → 立刻停，报告会话失效。",
  "2. 跑 py scripts/post_slot.py check。只有返回 0 才允许 publish；返回 3 或 4 → 这轮只做逛热搜、看社区高赞帖、拆写法卡、写草稿，绝不发布，也不许改配置绕过。",
  "3. 全篇只写《影之刃零》，别的游戏一个字都不写。",
  "4. 正文 >=1000 字（目标 1500-2500），>=3 张配图，分区必须同时挂 PC游戏 和 影之刃零（发布命令加 --topic \"影之刃零\"，核对打印出来的分区行）。",
  "5. 先运行 editorial.py audit 读已发正文的习惯和摘录；历史为空先核实旧文补录。填完整 .brief.json，运行 editorial.py plan 比较读者任务、证据路径、收尾与配图用途；可把所选 route 记入选题卡。发前运行 check_post.py 和 editorial.py review 新稿.md --require-brief，拦截项必须修复，重复提醒须核对实质增量。",
  "6. 按证据选推理路径，不默认社区吐槽开场、评分人数串联、总评后提问。评论热度不证明机制，总量均值不证明阶段分布，推断注明边界。每张图解释相应证据。排版检查仅提醒，不以换首图、小标题、篇幅冒充新内容。",
  "7. 每读一篇社区帖子，填全对应 .writing.json 的读者问题、论证顺序、证据用途、适用条件，再运行 editorial.py learn 保存可检索卡。",
  "8. 不许编造第一人称游玩经历；数据必须是查到的具体数字。",
  "9. 发布后核对：分区是 ['PC游戏','影之刃零']、正文无 .data/ 本地路径、图片已转存 imgheybox；然后 py scripts/post_slot.py record --link-id <id>。",
  "10. 任何一步失败（发布被拒、签名失败、分区解析失败）→ 停在草稿，不重试第二次，把原因写清楚。",
  "",
  "最后用中文简短汇报：这轮发没发、用了哪张写法卡、角度是什么、link_id、核对结果、下一轮该做什么。"
].join("\n");

// 只放**在子进程里验证过能用**的模型。
// 2026-10-30 实测：commandcode 在 `pi auth check` 里是 ready，但子进程里 401
// （Invalid Authorization header），所以不进链——加了只会多两次失败。
const models = [
  "deepseek/deepseek-flash",
  "deepseek/deepseek-v4-pro"
];

const attempts = [];
let done = null;

for (let i = 0; i < models.length; i++) {
  try {
    // runs.run 只有在子任务真的跑完时才 resolve；失败会 throw。
    // 别再拿 run.status 判断——这个字段根本不存在，之前就是这样误判的，
    // 一篇已经发出去了，还接着跑了两轮降级。
    const run = await runs.run("duty-" + i, {
      agent: "delegate",
      model: models[i],
      task
    });
    attempts.push({ model: models[i], ok: true, runId: run.runId });
    done = run;
    break;
  } catch (err) {
    attempts.push({ model: models[i], error: String((err && err.message) || err).slice(0, 300) });
  }
}

if (!done) {
  return { ok: false, tried: attempts };
}

return {
  ok: true,
  model: attempts[attempts.length - 1].model,
  tried: attempts,
  runId: done.runId,
  output: done.output
};
