# 梦幻西游口袋版自动化

目标是按游戏中已保存的角色，串联师门、抓鬼、副本与葫芦收尾四类任务。账号认证由用户人工完成。

已实现角色调度、抓鬼和乌鸡国／车迟国副本（新版名“车迟斗法”）；师门与抓鬼以游戏明确的完成卡片验收，持续执行直到完成。葫芦收尾自动开完宝库任务、副本分类的葫芦，并通过“丢弃所有”清空特殊葫芦。未见页面或无法识别的题型会保存现场停止；完整日常尚未完成设备验收。全部设备操作由触动精灵 Lua 状态机执行，MuMu 与电脑工具仅观察和采集证据。具体实现和限制见 [当前能力](docs/STATUS.md)、[葫芦收尾](src/tasks/rewards/README.md) 与 [抓鬼说明](src/tasks/zhuagui/README.md)。

## 代码入口

- `src/main.lua`：核对已保存角色，调度四类任务并汇总结果。
- `src/tasks/`：任务流程及其识别资源；两个副本的专用资源分别跟随 `wuji/`、`chechi/`。
- `src/common/`：识别、设备操作、已保存角色选择与主页导航。
- `src/dfx/` 与 `scripts/`：日志、截图、构建、发布、运行、采集。
- `参考代码/`：历史代码及来源记录，新入口不依赖它。
- `prototype/`：早期定位实验；`debug-runs/`、`dist/` 是忽略 Git 的运行产物。
- `tests/`：生产脚本测试；`testdata/`：冻结的输入、真值和预期。
- `scripts/perception/`：用例制作、审核与能力评测；`.tmp/annotation/`：临时标注数据。

结构见 [基线](docs/BASELINE.md)，副本机制见 [副本说明](src/tasks/dungeon/README.md)，运行结果与故障处理见 [DFX 说明](docs/DFX.md)。运行报告归档在 `debug-runs/`。

## 运行

在项目目录执行：

```powershell
python -m pip install -r scripts/requirements.txt
# 只观察，不点击
python scripts/device/run-daily.py --device emulator-5562 --mode observe
# 主循环；按配置任务持续执行至完成
python scripts/device/run-daily.py --device emulator-5562 --mode run --step daily
# 开发时只跑相关类别，不接触设备
python scripts/test.py --group 师门
# 合入前全量回归，默认上限60秒
python scripts/test.py
python scripts/perception/evaluate.py
```

运行器打包全部 Lua 模块，调用现有 CLI 发布到 TS Studio 与设备，校验哈希，等待退出并采集本轮日志、截图和结果。API 请求被接受不代表业务成功，需以设备日志和完成画面为准。

授权及角色配置位于仓库外的 `~/.my_pocket_automation/`。角色清单为 `daily-accounts.json`，例如 `[{"alias":"current"}]`；每个别名在 `accounts/<alias>/` 下具有私有的 `role.lua`（主页身份特征）和 `selector.lua`（已保存角色卡片特征）。别名与角色的绑定不能在同一天随意更换。

旧 `ts-cli.ps1` 的默认源码仍为登录实验，运行新主循环应使用上述运行器。新增角色、分辨率或改版页面须先观察、采集和校准，不应直接批量启动。
