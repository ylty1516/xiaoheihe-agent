# 影之刃零发帖值班手册

## 约束

本页只约束这项既有长文值班，不限制用户日常改稿、短帖或其他题材任务。

只发《影之刃零》，每 2 小时检查一轮，最多 3 篇/日，发布窗口 09:00–23:00。
分区 PC游戏(1) + 影之刃零(733575)。正文至少 1000 字，推荐 1500–2500，相关配图至少 3 张。
检查与发布显式选择 `--profile article`，不继承临时短帖的规格。
写作唯一规则见 docs/editorial-workflow.md；voice/profile.md 仅定义账号语气。

## 每轮流程

1. 跑 `py -m xhh_agent.cli.main doctor`。失败就停止。
2. 跑 `py scripts/post_slot.py check` 和 status。非 0 不发布，只学习或存本地草稿。
3. 看 `hot -n 5`、`topic-posts "影之刃零" -n 10`；找到读者问题并查原始来源。
4. 运行 `editorial.py audit`，读最近已发正文摘录和 `editorial.py library` 中适用的卡。
   不能只看标题；历史为空先核对旧文补录。没有新问题或新证据就不硬写。
5. 新建 post-*.brief.json，填全选题卡，明确本篇不再展开的旧内容。
6. `editorial.py plan` 比较读者任务、推理路径、收尾与配图用途，按证据选择路线。
   不靠换标题、堆平台数字或编出实测制造多样。评论和总量数据不能越界支持普遍结论。
7. 写正文，跑 `check_post.py 新稿.md --profile article`、`editorial.py review 新稿.md --require-brief`。
   拦截项必须修复；重复线索必须逐段判断并说明增量，不能仅换排版后忽略。
8. 跑 `style_profile.py compare 新稿.md`，只作节奏建议。允许不同主题使用相同排版。
9. 用 draft + --html-out 检查排版；排期允许时按既有授权 publish --edit-link 草稿ID --yes。
10. fetch_post_detail 核对公开状态、两个分区和图片；再 post_slot.py record 登记排期。
    CLI 成功公开后自动写入内容记忆，不要再把草稿手动导入。失败或结果不明停下核对。

## 学习

study 产生正文笔记和 pending 写法卡。选择值得复用的样本填写读者问题、论证顺序、证据用途、适用条件，
运行 editorial.py learn 保存为 ready。只抓下来不算学完。

## 汇报

简短说明本轮是否发布、核心问题、独有证据、所选结构、link_id 与核对结果。
发布已成功而本地登记失败时，明确“已公开，勿重发”，核对后补录。
