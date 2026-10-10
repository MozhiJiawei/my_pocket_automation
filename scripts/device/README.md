# 设备构建与调试

本目录负责构建、发布、运行、采集和设备诊断，不负责标注制作或离线能力评分。

| 文件 | 职责 |
|---|---|
| `build.py` | 从仓库源码生成 Lua 发布包及哈希清单。 |
| `run-daily.py` | 构建、发布、运行、等待、采集并验证业务证据。 |
| `ts-cli.ps1` | 发布、启动、查询状态和采集；发布前检查空闲状态并校验哈希。 |
| `collect-debug.ps1` | 采集指定设备和轮次的日志、截图及结果。 |
| `inspect-device.py` | 观察当前画面，按已验证条件执行开发调试操作。 |
| `dfx_device.py` | 共用设备通信、命令执行与请求实现。 |

使用仓库根目录的 [项目说明](</D:/Agent Repo/my_pocket_automation/README.md>) 查看运行参数和费用边界；具体故障处理见 [DFX 说明](</D:/Agent Repo/my_pocket_automation/docs/DFX.md>)。运行器用于当前主循环，CLI 的默认源码仍是早期登录实验，直接使用时须明确目标源码。
