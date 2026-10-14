# 设备构建与调试

本目录负责构建、发布、运行、采集和设备诊断，不负责标注制作或离线能力评分。

| 文件 | 职责 |
|---|---|
| `build.py` | 从仓库源码生成 Lua 发布包及哈希清单。 |
| `run-daily.py` | 构建、发布、运行、等待、采集并验证业务证据。 |
| `ts-cli.ps1` | 发布、启动、查询状态和采集；发布前检查空闲状态并校验哈希。 |
| `collect-debug.ps1` | 按轮次归档、校验日志和截图，清理已结束轮次的设备副本。 |
| `inspect-device.py` | 只读截图与 OCR 诊断，不发送任何页面操作。 |
| `dfx_device.py` | 共用设备通信、命令执行与请求实现。 |

使用仓库根目录的 [项目说明](</D:/Agent Repo/my_pocket_automation/README.md>) 查看运行参数和费用边界；具体故障处理见 [DFX 说明](</D:/Agent Repo/my_pocket_automation/docs/DFX.md>)。运行器用于当前主循环，CLI 的默认源码仍是早期登录实验，直接使用时须明确目标源码。

采集先拉到临时文件，通过设备端与本地 SHA256 校验后替换归档。整轮文件已校验后，只有主日志末行明确记录脚本结束，或通过现有授权接口确认触动精灵空闲，才逐个清理设备副本，主日志最后删除。没有结束日志且无法确认空闲时只采集；运行中或校验失败时保留设备文件。仅处理项目命名的日志和截图，不清理 Lua 资源、配置或进度账本。`run-daily.py` 自动传递临时授权用于空闲检查，采集本身不要求授权。

## 已保存角色轮转

设备操作统一在触动精灵 Lua 状态机执行。电脑端仅构建、发布、启动 Lua、采集与验证证据，不通过 MuMu、ADB 或电脑 OCR 点击、滑动、按键、启动或重启游戏。识别或拼图失败会停止本轮，非识别流程问题修改 Lua 后发布复测。

`--step daily --tasks shimen,zhuagui,dungeon --select-accounts <别名1> <别名2>` 配置本轮的多个角色和任务范围。完整已登录名单仍由 `--accounts <仓库外配置.json>` 提供；Lua 核对完整名单后只执行选中角色，按名单顺序运行。`--account <别名>` 选择单角色；省略角色选择则遍历配置中的全部角色。身份、进度和预算按角色隔离。

`run-daily.py --mode run --step daily --tasks zhuagui,dungeon --zhuagui-budget 75 --max-seconds 10800 --device emulator-5562` 遍历外部配置的全部已登录角色，核对选择页名单与每次进入后的身份。遇到未配置卡片或名单不完整时暂停，不遗漏新角色。

`~/.my_pocket_automation/daily-accounts.json` 保存稳定别名与逐角色策略；身份、选择特征由 `calibrate-role.py` 保存到同一外部配置目录。别名不得重新绑定其他角色，既有进度按业务日期和别名隔离。新角色需要先从已登录选择页和主页校准身份资源；工具不输入账号密码。

每个角色可配置 `claim_dungeon_rewards` 和 `dungeon_reward_budget`（0、100、200）。默认禁止领取；只有已授权角色、已完成副本、确认100精力按钮与预算都满足时才发送一次现场破解封印请求。请求先保存，未知结果不重复点击。宝库开葫芦由独立的 `rewards` 收尾模块处理。

`--account <已配置别名>` 用于有界的单角色恢复；与 `--step daily` 组合时，核对全名单后仅运行指定角色，汇总范围为 `selected_roles`，不会报告全部角色完成。副本接管已有战斗只被动等待；抓鬼可推进已记录任务的免费对话、寻物和重试。身份未核对时不新接任务，不记录抓鬼完成；返回待接取页面后先核对主页身份。

每个副本默认最多等待60分钟，覆盖连续多场战斗；运行器默认完整流程等待10800秒，`complete/advance` 等待3900秒，`--max-seconds` 可明确设置电脑端上限。超时保留已启动记录，先检查现场再恢复，不重新开启副本。

`--zhuagui-target 10 --zhuagui-budget 30 --dungeons wuji` 配置每日第10次抓鬼目标、30精力预算及乌鸡国范围，不执行车迟国。抓鬼以页面次数验证完成，达到本轮目标不把整日25次记为已完成。预算保护存在未修复缺口，配置值不能保证实际消耗上限，见 `docs/STATUS.md`。寻物识别失败最多免费重试3次，先保存错误现场；其他页面错误不触发该重试。

运行器默认开启 Profile。`daily_<轮次>.log` 保存关键状态与结果，`_error.log` 保存错误与截图路径，`_profile.log` 保存调用次数、累计耗时、最大耗时与 CPU 时间。常规截图和逐次点击日志默认关闭；仅在专项采集时显式启用配置中的 `routine_screenshots` 或 `verbose_logs`。


`selected_complete` 表示本轮所选范围内的角色都完成所选任务；指定单角色时不能据此称作全部角色完成。`daily_complete` 只有全部配置角色的师门、抓鬼、副本、葫芦收尾四类都完成时才为真。默认任务顺序为 `shimen,zhuagui,dungeon,rewards`，显式选择也按该顺序执行。师门仅覆盖已采集页面与已确认题型，不能把部分任务当作全部日常完成。

葫芦调测使用 `--task rewards --mode run --step complete --account <别名> --rewards-debug-after-shimen`：Lua 核对该角色师门完成卡片后，自动开光宝库任务、副本葫芦并丢光特殊葫芦。`enter/browse` 只看列表或详情，可用 `--rewards-inspect-category task|dungeon|special` 采集；`advance` 只执行一次业务动作。调测不记开启数量，也不会报告 `daily_complete`。



师门已有任务使用 run-daily.py 的 --task shimen --mode run --step advance --account <别名> 单步推进；--step complete 在交付、身份与次数核对后继续领取下一项，并通过列表中的师门已完成卡片验证第20次交付。设备 Lua 负责全部操作；寻物首次尝试后最多免费重试3次，拼图先匹配旧特征中的唯一题型，不能识别或不能完成则保存现场停止。新业务日仅在角色、空闲页与零次数核对后建立账本；跨日活动任务须显式指定 --shimen-resume-date <旧账本日期>，保留重试次数并隔离两日进度。免费重试分支和未见题型尚未全部设备验证；未知页面有界等待后仍会停止。
