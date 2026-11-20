# 项目协作规则

## 1. 运行标准与入口

- **目标是 Lua 独立完成配置范围内的每日任务。** 游戏中的身份核验、导航、识别、交互、重试、中断恢复和收尾均由 Lua 执行。AGENT 负责观察画面与日志、修改源码、回归、发布和复测，禁止通过 MuMu、ADB 或电脑端工具操作游戏。账号认证由用户完成。
- Lua 操作前验证状态，操作后验证结果；单次等待与操作必须有时限，无法判断时留证。启动、发布前确认接口空闲并校验产物；忙碌或状态未知时不发布，启动结果未知时先取证，不盲目重发同一启动请求；恢复重启按下文失败处理执行。
- **允许持久化每日任务白名单内的完成布尔状态。** 记录按角色别名、身份绑定和业务日隔离，仅由 Lua 核验游戏最终业务状态后写入；身份与业务日匹配的已完成状态可跨运行复用。任务内部阶段、次数和重试只保留在内存，未完成任务从游戏页面恢复。已核验状态仅在缺失、失效或动作预期变化时重新获取；日志、截图和调试报告不作为业务状态。
- 完成验收须覆盖全部所选角色与任务。请求成功、点击发送、进程存在或脚本退出均不能单独证明业务完成；应用入口就绪与日常完成分别验收。离线通过不能替代设备验收，单次成功不能宣称稳定。
- INFO 保留角色、任务起止、验收、恢复重试和最终结果；页面、识别、输入与等待细节归 DEBUG。默认不归档常规过程和成功页面，失败、待验收、领奖收据及显式采集按需留证，每轮源码版本和运行证据归档到 `debug-runs/`。

### 运行入口

在仓库根目录执行，实例索引、设备地址和角色范围按本次配置选择：

| 用途 | 入口 |
|---|---|
| 验收完成后停止实例并清理残留虚拟机进程 | `python scripts/device/stop-emulator.py --vm-index <实例索引>` |
| 启动环境并单次调用 Lua | `python scripts/device/start-emulator.py --vm-index <实例索引> --mode run --step daily` |
| 只读截图与诊断 | `python scripts/device/inspect-device.py --device <设备>` |
| 由 Lua 观察游戏页面 | `python scripts/device/run-daily.py --vm-index <实例索引> --mode observe --step observe` |
| 环境已就绪时单次执行每日任务 | `python scripts/device/run-daily.py --vm-index <实例索引> --mode run --step daily` |

两个正式执行命令都必须指定 `--vm-index`，默认参数均为 `--mode observe --step observe`；`--device` 仅作可选的一致性核验。`start-emulator.py` 在环境就绪后按原角色、任务和步骤范围调用 Lua 一次；`--force-restart` 明确要求先重启指定实例一次。构建、发布、等待、采集及结果核验复用现有运行器，共享实例锁只防止并发，不管理恢复次数。命令、范围参数及恢复记录模板见[设备脚本说明](</D:/Agent Repo/my_pocket_automation/scripts/device/README.md>)；授权、角色配置及身份资源位于仓库外的 `~/.my_pocket_automation/`。分析运行结果与故障时读 [DFX 说明](</D:/Agent Repo/my_pocket_automation/docs/DFX.md>)。

### 每日运行进展监控

每日运行由**每5分钟到达的定时器消息**驱动 AGENT 监控。每条消息执行一次“监控取证 → 确认状态 → 选择处理”，需继续监控时等待下一条5分钟消息；消息本身不触发重新运行 Lua，也不重置恢复次数。

**完成当前检查和处理后立即释放会话。** 初次启动完成本次有界状态确认并确保5分钟监控定时器已启用后，以及每次定时器消息触发的检查、取证和本次必要处理完成后，AGENT 都应结束当前回复、释放会话，由下一条5分钟消息重新唤醒。“等待下一条消息”指释放会话后的等待，禁止用 `sleep`、空等、循环查询或反复轮询长运行命令输出来占着会话等定时器。后台运行器、Lua 和监控定时器继续运行；完成验收或按规则交接后，再结束本轮监控。

1. **监控取证。** 沿用原命令的 MuMu 安装目录、实例和范围，以本次 Lua 的 `debug-runs/<Lua轮次>/result.json` 核对 `vm_index`、`device`、`adb`、`run_id` 和 `requested_scope`，不混用环境启动轮次或其他实例。每次检查均有时限，授权不得输出或归档。
2. **确认状态。** 将本轮接口状态、新增日志与画面交叉核对，确认当前角色、任务及最后可确认的业务进展：
   - **Lua 状态：** 通过 `scripts/device/dfx_device.py` 的 `Device.authorize()`、`status()` 查询，结束后 `close()`。`f01` 表示有脚本运行，须结合本轮日志确认是本次 Lua；`f00` 仅表示接口空闲，`f02` 表示录制，查询失败或未知返回保持状态未知。运行中的 `result.json` 是先前快照，不是实时心跳。
   - **日志：** 用本轮 ADB 与设备执行 `shell tail -n 80 /storage/emulated/0/TouchSprite/log/daily_<Lua轮次>.log`，并按需读取同目录 `_error.log`；采集后看 `debug-runs/<Lua轮次>/log/`。对照角色、`task_start`、`task_result`、`home_verified`、恢复重试及结束事件；默认 INFO 不逐次记录等待，短期无新增不能判定卡死。
   - **画面：** 需要核实推进时，用 `python scripts/device/inspect-device.py --device <本轮设备> --no-ocr` 只读截图，先确认其 ADB 路径与本轮一致；也可用本轮 ADB 的 `shell screencap -p <设备临时PNG>`、`pull` 拉取。打开本地 PNG，与上次画面和日志对照角色、任务文本、回合、计数、倒计时及页面阶段；截图成功、动画变化或单张静止画面均不能单独证明推进或停滞。
3. **选择处理。** 按以下分支处理，恢复条件、顺序和次数统一遵守下方“运行期失败处理”：

| 确认的状态 | 本次处理与后续 |
|---|---|
| Lua 正在推进，或处于所属任务允许的有界等待 | 记录当前角色、任务与进展，释放会话，等待下一条5分钟消息。 |
| Lua 仍在运行但进展待确认、处于录制，或运行状态未知 | 只读补充日志、截图等证据，记录未知项，释放会话，等待下一条5分钟消息；不另发 `observe`、`run`、发布、强停或重启。 |
| 已确认拼图识别失败，且 Lua 已结束、接口空闲 | 进入拼图识别处理流程，按[识别工具说明](</D:/Agent Repo/my_pocket_automation/scripts/perception/README.md>)还原、自查、校准、回归及受控复测；同一题型方案最多3次设备检验，复测启动后完成本次有界状态确认即释放会话，继续由5分钟消息驱动监控。 |
| 其他运行期故障，原范围未完成，且 Lua 已结束、接口空闲 | 进入恢复流程：动作前更新恢复记录，保持已验证版本与原范围，按规定先做 Lua 恢复，仍失败再重启指定实例；每次恢复启动后完成本次有界状态确认即释放会话，继续由5分钟消息驱动监控。 |
| 本轮已结束且全部所选角色与任务验收通过 | 核对本轮 `[finished]`、`[summary]`、逐角色任务结果和 `result.json`，报告结果并结束本轮监控。 |
| 无法安全继续、恢复次数耗尽、需要账号认证或缺少必要授权、证据 | 保存证据与未完成范围，按失败处理要求交接用户。 |

### 运行期失败处理

单次命令失败后由 AGENT 读取原始结果、日志、失败画面与源码版本，判断首个故障、Lua 是否仍在运行及原范围是否已验收，再决定下一步。Lua 仍在运行或状态未知时仅观察和取证，不从外部强停 Lua、不覆盖代码、不重发启动，也不因游戏进程是否存活而干预。Lua 内部已有的有界游戏重启和免费重试继续保留；Python 命令不自动编排后续恢复。

AGENT 按以下顺序处理，并在每次恢复动作前手工更新 `debug-runs/recovery/vm-<实例索引>/恢复记录.md`：

1. 固定目标安装目录、实例、原命令范围和已验证版本，核对源码、构建包、配置及角色身份和选择资源哈希；先承接同目标仍未解除的历史故障，不把新会话当作新故障。
2. 拼图失败按[识别工具说明](</D:/Agent Repo/my_pocket_automation/scripts/perception/README.md>)独立还原、自查、校准、回归及受控复测，允许按该流程修改源码并归档各版本。同一题型方案最多3次设备检验，与普通恢复和 Lua 免费重试独立计数。
3. 其他运行期故障保持已验证版本及原角色、任务、步骤范围，不动态修改源码、识别资源、参数或验收条件。初次执行不计恢复；确认 Lua 已结束且接口空闲后，同一未解除故障最多额外调用 `run-daily.py` 3次，仍失败再最多调用带 `--force-restart` 的 `start-emulator.py` 3次。每次实例重启附带的一次 Lua 验证只计实例恢复，不再占 Lua 恢复次数，也不重开 Lua 配额。
4. 动作发出前预记本层次数、依据和关联证据；确定未发请求才撤销本次预记，请求结果未知则保守保留并先取证。同故障的原因文字、命令、会话或进程变化均不清零；只有 AGENT 根据新证据确认旧故障解除，才记录结论并为后续独立故障建立新预算。无关任务完成、请求成功或脚本退出不能解除旧故障。
5. 每周二北京时间 `07:30 <= 当前时间 < 09:00`，所有非拼图故障统一放宽上述恢复次数，仅按时间判断，不要求维护原因或确认文件；仍逐次预记、串行执行、有界等待并取证。窗口结束立即按累计次数执行普通上限，计数不清零；拼图方案检验上限不放宽。
6. 无法安全继续、恢复次数耗尽、需要账号认证、缺少授权或无法自主取得必要证据时，记录结果、未完成范围与下一步并交接用户。原自动恢复历史保留，未解除故障须由 AGENT 承接；恢复记录只供诊断，不作为 Lua 业务进度。

## 2. 开发架构与入口

Lua 是设备业务执行层，Python 与 PowerShell 是电脑端开发和运行工具，标注网页维护识别输入与真值。Lua 入口为 [main.lua](</D:/Agent Repo/my_pocket_automation/src/main.lua>)，每日调度为 [daily.lua](</D:/Agent Repo/my_pocket_automation/src/daily.lua>)；任务模块复用公共能力，日志和取证由 DFX 提供。运行期进度由 [progress.lua](</D:/Agent Repo/my_pocket_automation/src/progress.lua>) 管理，每日完成状态白名单及持久化由 [completion.lua](</D:/Agent Repo/my_pocket_automation/src/completion.lua>) 管理。

| 目录 | 职责与按需阅读入口 |
|---|---|
| `src/` | Lua 入口、调度及状态管理；架构约定见[基线](</D:/Agent Repo/my_pocket_automation/docs/BASELINE.md>)。 |
| `src/tasks/` | 任务状态机及所属识别资源；修改任务时读[师门](</D:/Agent Repo/my_pocket_automation/src/tasks/shimen/README.md>)、[抓鬼](</D:/Agent Repo/my_pocket_automation/src/tasks/zhuagui/README.md>)、[副本](</D:/Agent Repo/my_pocket_automation/src/tasks/dungeon/README.md>)或[葫芦收尾](</D:/Agent Repo/my_pocket_automation/src/tasks/rewards/README.md>)说明。 |
| `src/common/` | 共享识别、设备输入、角色与页面导航；修改公共能力时读[公共模块说明](</D:/Agent Repo/my_pocket_automation/src/common/README.md>)。 |
| `src/dfx/` | 日志、截图、素材与性能诊断；修改取证或结果处理时读 [DFX 说明](</D:/Agent Repo/my_pocket_automation/docs/DFX.md>)。 |
| `scripts/` | 开发工具；设备运行读[设备说明](</D:/Agent Repo/my_pocket_automation/scripts/device/README.md>)，识别校准、标注固化及素材补采读[识别工具说明](</D:/Agent Repo/my_pocket_automation/scripts/perception/README.md>)。 |
| `annotation-web/` | 标注网页及待确认、已确认队列；标注作业读[标注器说明](</D:/Agent Repo/my_pocket_automation/annotation-web/README.md>)，队列内容不提交。 |
| `tests/` | 生产实现的流程、识别及回放测试与离线设备替代环境；选测与分类见[测试说明](</D:/Agent Repo/my_pocket_automation/tests/README.md>)。 |
| `testdata/` | 实际回归使用的原图、唯一答案、业务预期和格位配置；数据约定见[用例说明](</D:/Agent Repo/my_pocket_automation/testdata/README.md>)。 |
| `docs/` | 当前设计、使用说明和[能力边界](</D:/Agent Repo/my_pocket_automation/docs/STATUS.md>)。 |
| `参考代码/`、`prototype/` | 历史实现与独立实验；正式入口不得依赖。 |
| `.tmp/`、`debug-runs/`、`dist/` | 临时缓存、运行归档及自动构建产物；均不提交，`dist/` 不手工维护。 |

| 开发用途 | 入口 |
|---|---|
| 安装依赖 | `python -m pip install -r scripts/requirements.txt` |
| 相关类别回归 | `python scripts/test.py --group 师门`；可组合类别，详见测试说明。 |
| 全量回归 | `python scripts/test.py`；须在本机60秒内完成，提速不得减少范围或检查项。 |
| 构建发布产物 | `python scripts/device/build.py`；设备复测使用上述正式运行入口。 |

- 默认在 `master/main` 工作，不擅自切分支或创建 worktree；子 Agent 不 fork 上下文。
- 不自行新增顶层目录或改变目录职责；公共能力统一复用，测试调用生产实现，不另造识别算法。任务业务规则、页面特征、参数和操作步骤维护在所属实现、测试及模块 README，不重复写入根 AGENTS.md。
- 运行失败按上文“运行期失败处理”执行。开发时运行相关类别测试，交付前运行全量回归；文档整理核对入口、链接与规则一致性，不因此启动设备。
- `testdata/` 只保留实际回归使用的原图、`答案.json`、`预期.json`、`格位.json` 及目录 README；采集、审核、来源、建议及更正过程留在标注队列或 `debug-runs/`，不另建替代侧车文件。未标区域保持未知，识别器输出不能自证真值，AGENT 自查不能记作人类确认。
- 正式文档只记录当前规则与能力，运行历史留在 `debug-runs/`；同一规则在所属文档维护，其他入口按需链接。
