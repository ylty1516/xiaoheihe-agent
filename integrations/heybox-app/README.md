# 本机小黑盒App执行组件

Python通过私有JSONL stdin/stdout调用本模块。Node.js至少24；安装与首次授权见[每日任务说明](../../docs/daily-tasks.md)。凭据留在项目`.data/app/`，不使用第三方托管服务。不要单独暴露worker进程或把本机后端映射到公网。

运行代码在`lib/`，`vendor/`保留上游MIT源码和来源摘要。来源提交`15d6f3c3537a2914fbef8098d5306b9a7529924c`。`build.mjs`先校验所有规范化LF源码，再用Node内置类型擦除构建JS；唯一集成修改是把登录时的固定任务ID校验改成`account-check.mjs`的账号与清单校验，任务执行仍独立校验支持的ID和名称。

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm test
```

`test/native-v14.json`保留原生签名对照数据。测试不使用真实手机号、账号或模型，不发送短信。依赖通过package-lock固定；不安装或执行Android资源、Java组件和上游托管站。设备授权SDK按源码中的固定SHA256验证后执行。

分享执行明确采用流程上报，不能当成消息实际送达的证明。未适配任务（如部分账号的任务11）保留未完成。组件版本0.1.0，Python集成版本0.8.0。
