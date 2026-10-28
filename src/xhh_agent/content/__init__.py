"""排版层：把 agent 产出的 Markdown 变成小黑盒能正确渲染的 HTML。

职责：
- Markdown → 小黑盒 HTML（白名单有限，代码块/表格是重灾区）
- 图片上传前置处理（尺寸探测、格式校验）
- 字数、标题长度校验（超限在本地拦截，不发出去被拒）

约束：
- 不碰网络（图片上传由 protocol 层负责）
- 纯函数，输入输出都可用快照测试比对

参照：xiaoheihe-cli 的 markdown_converter.py（MIT）
"""
