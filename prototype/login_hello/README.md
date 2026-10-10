# 口袋版自动登录原型

这是一个全新原型，不依赖仓库中的旧业务脚本。第一版只验证两件事：

1. 触动精灵能加载新 Lua 文件；
2. 能启动包名为 `com.netease.mhxyhtb` 的口袋版。

## 在 IDE 中运行

1. 将 `main.lua` 加入一个新工程。
2. 连接已经配置好的 MuMu 设备。
3. 发送并运行 `main.lua`。
4. 从日志读取 `Hello World：新登录原型已启动`，等待口袋版打开。
5. 脚本会在启动前、启动后自动截图，并在 IDE 输出带有 `[hello_world]` 前缀的日志。
6. 记下日志中的运行编号，例如 `20261009_143000`。
7. 告诉助手运行完成，助手执行 Windows 收集脚本取回日志和截图，无需手动复制。

## Windows 自动收集

也可以用统一 CLI 替代 IDE 的发送操作：

```powershell
& 'D:/Agent Repo/my_pocket_automation/scripts/device/ts-cli.ps1' deploy
& 'D:/Agent Repo/my_pocket_automation/scripts/device/ts-cli.ps1' status
& 'D:/Agent Repo/my_pocket_automation/scripts/device/ts-cli.ps1' run
& 'D:/Agent Repo/my_pocket_automation/scripts/device/ts-cli.ps1' collect
```

`deploy` 同步 TS Studio 和设备文件，并校验 SHA256。`run` 先检查空闲状态，再发布并通过官方 API 启动；`run/status` 需要环境变量 `TOUCHSPRITE_AUTH`，它是官方中控 API 验证串，与 VIP 激活码不同。没有验证串时，可以先 `deploy`，在设备上手动运行，然后 `collect`。`hello_world_004` 已移除信息弹框和 toast，结果写入日志并正常退出；CLI 启动请求成功不代表业务步骤成功。

官方接口参考：[设置脚本路径](https://helpdoc.touchsprite.com/dev_docs/2183/437/441/456.html)、[运行脚本](https://helpdoc.touchsprite.com/dev_docs/2183/437/441/457.html)、[获取验证串](https://helpdoc.touchsprite.com/dev_docs/2183/437/441/445.html)。

在 PowerShell 中执行（不依赖当前工作目录）：

```powershell
& 'D:/Agent Repo/my_pocket_automation/scripts/device/collect-debug.ps1'
```

按运行编号归档到 `D:/Agent Repo/my_pocket_automation/debug-runs/<运行编号>/log/` 和 `D:/Agent Repo/my_pocket_automation/debug-runs/<运行编号>/res/`。脚本仅收集本原型的日志和截图，不删除设备文件。

使用 `-RunId 20261009_180002` 可以只取指定轮次；使用 `-Watch` 持续每 5 秒同步，Ctrl+C 停止。需要 ADB 设备在线；多设备时指定 `-Device`，无法自动找到 ADB 时指定 `-AdbPath`。

## 下一步

登录流程会按真实画面逐步实现：

1. 识别登录页；
2. 点击账号输入框；
3. 输入账号和密码；
4. 点击登录；
5. 识别登录成功后的主页；
6. 遇到异常弹窗时停止并报告。

账号密码不会写入仓库，后续通过 MuMu 内部的本地配置提供。

## 调试约定

- 每个阶段使用固定的阶段名，例如 `login_page_detected`、`account_entered`。
- 阶段开始和失败时自动截图。
- 日志只记录状态、耗时和错误，不记录账号密码。
- 图片识别优先使用相对坐标、锚点或模板，避免绑定单一分辨率。
