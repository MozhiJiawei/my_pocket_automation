# 测试与识别工具目录迁移

目录边界见 [AGENTS.md](</D:/Agent Repo/my_pocket_automation/AGENTS.md>)；本文件只记录迁移验证。

生产脚本测试留在 `tests/`，离线 Lua 环境迁入 `tests/support/`。正式输入与预期迁入 `testdata/`；导入、拼接、标注、审核和评测迁入 `scripts/perception/`，20 项工具测试跟随工具。标注工作数据迁入 `.tmp/annotation/`，已审核更正依据留在 `testdata/zhuagui/annotation-history/`。既有审核展示产物归档于 `debug-runs/20261010_174000/annotation-review/`；新审核工具只向独立 `debug-runs/` 目录输出图片与页面。

迁移时核对 709 个既有证据文件，内容哈希全部一致。原始截图、正式真值及预期未改。所有活动源码和文档引用已更新，不保留旧路径兼容入口。

验证：70 项生产脚本测试通过（148 秒），20 项工具测试通过（28 秒）；新入口成功生成黄金整轮长图和单物品审核图。单帧能力评测继续保留黄金未识别失败；完整 502 帧能力结果仍为通过 1006、失败 177、未评分 281，71 轮中通过 7、失败 62、未评分 2。目录迁移没有修复或掩盖算法能力缺口。

```powershell
python -m unittest discover -s tests
python -m unittest discover -s scripts/perception/tests -t .
python scripts/perception/evaluate.py
```

本次没有连接游戏执行任务、发布脚本或消耗精力。

后续按用户要求合并工具入口：设备工具统一到 `scripts/device/`，识别与用例工具统一到 `scripts/perception/`；删除顶层 `tools/`，更新 Python 导入、PowerShell 根目录计算、主运行器及登录实验的调用路径。依赖清单保留在 `scripts/requirements.txt`。

合并后 70 项生产脚本测试通过（162 秒）、20 项工具测试通过（33 秒）；新路径本地构建成功，发布包 Lua 编译检查通过。设备运行、诊断和采集索引命令的帮助入口均能加载，未实际发布或操作游戏。
