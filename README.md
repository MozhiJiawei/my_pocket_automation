# 梦幻西游口袋版自动化

目标是按游戏中已保存的角色，串联师门、抓鬼、副本、葫芦与活跃度处理四类任务。账号认证由用户人工完成。

已实现主循环和乌鸡国、车迟国副本（新版界面名“车迟斗法”），并在当前角色上各实测通关一次，副本未领取奖励。抓鬼已实测野鬼、马面、僵尸、蛇胆酒、骷髅怪寻物及战斗，最新次数与费用见 [抓鬼实测报告](docs/ZHUAGUI_TEST_REPORT.md)；其他酒类、四格拼图和整日 25 次循环尚未验收。师门、收尾处理仍为 `not_implemented`，整日清单未完成。葫芦保持未开启。实现与运行见 [抓鬼适配说明](src/tasks/zhuagui/README.md)。

## 代码入口

- `src/main.lua`：核对已保存角色，依次调用四类任务，遇到阻塞停止。
- `src/tasks/`：任务流程及其识别资源；两个副本的专用资源分别跟随 `wuji/`、`chechi/`。
- `src/common/`：识别、设备操作、已保存角色选择与主页导航。
- `src/dfx/` 与 `scripts/`：日志、截图、构建、发布、运行、采集。
- `参考代码/`：历史代码及来源记录，新入口不依赖它。
- `prototype/`：早期定位实验；`debug-runs/`、`dist/` 是忽略 Git 的运行产物。
- `tests/`：生产脚本测试；`testdata/`：冻结的输入、真值和预期。
- `scripts/perception/`：用例制作、审核与能力评测；`.tmp/annotation/`：临时标注数据。

结构与后续范围见 [基线](docs/BASELINE.md)，机制见 [副本说明](src/tasks/dungeon/README.md)，本轮证据与限制见 [实测报告](docs/DUNGEON_TEST_REPORT.md)，运行结果与故障处理见 [DFX 说明](docs/DFX.md)。

## 运行

在项目目录执行：

```powershell
python -m pip install -r scripts/requirements.txt
# 只观察，不点击
python scripts/device/run-daily.py --device emulator-5562 --mode observe
# 主循环；当前抓鬼默认零预算，会在接任务前阻塞
python scripts/device/run-daily.py --device emulator-5562 --mode run --step daily
# 离线回归，不接触设备
python -m unittest discover -s tests -p "test_*.py"
python -m unittest discover -s scripts/perception/tests -t .
python scripts/perception/evaluate.py
```

运行器打包全部 Lua 模块，调用现有 CLI 发布到 TS Studio 与设备，校验哈希，等待退出并采集本轮日志、截图和结果。API 请求被接受不代表业务成功，需以设备日志和完成画面为准。

授权及角色配置位于仓库外的 `~/.my_pocket_automation/`。角色清单为 `daily-accounts.json`，例如 `[{"alias":"current"}]`；每个别名在 `accounts/<alias>/` 下具有私有的 `role.lua`（主页身份特征）和 `selector.lua`（已保存角色卡片特征）。当前只实测了一个角色；别名与角色的绑定不能在同一天随意更换。

旧 `ts-cli.ps1` 的默认源码仍为登录实验，运行新主循环应使用上述运行器。新增角色、分辨率或改版页面须先观察、采集和校准，不应直接批量启动。
