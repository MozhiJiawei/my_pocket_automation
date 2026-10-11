# 生产脚本测试

本目录只保存生产脚本的测试代码与必要的离线设备替代环境。用例数据位于 `testdata/`；用例制作、人工审核和能力评测入口位于 `scripts/perception/`，不得迁回本目录。

| 目录 | 验证范围 |
|---|---|
| `unit/` | 主流程、费用与次数保护、动作重验证、DFX 及发布保护、Lua 语法。 |
| `perception/` | 正式用例的数据完整性、真实 Lua 识别回归、电脑找色接口契约。 |
| `replay/` | 指定画面序列下，目标消失或移动后的真实动作重验证。 |
| `support/` | Lua 加载器与离线触动接口替代实现，不连接设备。 |

```powershell
python scripts/test.py
```

统一入口同时运行生产测试和工具测试，并检查总耗时不超过 30 秒。独立画面并行评测，增强图直接在内存生成；每张图仍执行实际 Lua 识别和真值校验，失败增强图才保存到 `.tmp/`。可用的 OpenCL GPU 批量执行大区域找色，小区域留在 CPU；`POCKET_TEST_GPU=off` 可切回 CPU 对照，`required` 可禁止静默回退。依赖见 `scripts/requirements.txt`。其它机器可用 `--max-seconds` 调整性能门槛。

只运行生产测试仍可使用 `python -m unittest discover -s tests`。

Lua 模块只缓存编译后的源码，不缓存模块实例或识别答案；每张画面仍使用独立虚拟机，源码内容变化会重新编译。发布保护场景在一次 PowerShell 启动中逐项重置、执行和断言。

数据读取、校验与评分共用 `scripts/perception/lib/`。目录与局部真值提供回归预期；全部已确认的评分失败都会使测试失败，新修复场景不能仅留在报告里。待审核或部分真值的未知区域保持未评分。评测结果另存 `debug-runs/<运行编号>/offline-evaluation/`；离线通过不证明设备业务完成。

用例维护与评测见 [工具说明](</D:/Agent Repo/my_pocket_automation/scripts/perception/README.md>)；目录边界见 [协作规则](</D:/Agent Repo/my_pocket_automation/AGENTS.md>)。
