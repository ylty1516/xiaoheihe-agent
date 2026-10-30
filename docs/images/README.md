# 截图放这里

README 会引用这几个文件：

| 文件名 | 内容 | 怎么来的 |
|---|---|---|
| `post.png` | 小黑盒 App 里帖子的效果图（能看出排版、加粗、小标题） | 手机实拍 |
| `webui.png` | `heihe auto` 打开的本地面板 | Chrome headless 截的，要重拍见下 |
| `cli.png` | 终端跑 `xhh` 命令的截图（可选） | 还没有 |

## 重拍 webui.png

```powershell
# 1. 起服务（不要开浏览器）
py -m xhh_agent.cli.main auto --no-open --port 8765

# 2. 另开一个窗口截图
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu `
  --hide-scrollbars --window-size=1360,1210 --virtual-time-budget=6000 `
  --screenshot="docs/images/webui.png" "http://127.0.0.1:8765/"
```

`--virtual-time-budget` 是必须的：页面是靠 JS 拉 `/api/state` 渲染的，
给的时间不够会截到一片"--"。
