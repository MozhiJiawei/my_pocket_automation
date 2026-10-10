# 生产脚本测试

本目录只保存生产脚本的测试代码与必要的离线设备替代环境。用例数据位于 `testdata/`；用例制作、人工审核和能力评测入口位于 `scripts/perception/`，不得迁回本目录。

| 目录 | 验证范围 |
|---|---|
| `unit/` | 主流程、费用与次数保护、动作重验证、DFX 及发布保护、Lua 语法。 |
| `perception/` | 正式用例的数据完整性、真实 Lua 识别回归、电脑找色接口契约。 |
| `replay/` | 指定画面序列下，目标消失或移动后的真实动作重验证。 |
| `support/` | Lua 加载器与离线触动接口替代实现，不连接设备。 |

```powershell
python -m unittest discover -s tests
```

数据读取、校验与评分共用 `scripts/perception/lib/`。回归基线只包含旧评测实际通过的断言；全量识别能力结果另存 `debug-runs/<运行编号>/offline-evaluation/`。测试方法通过不代表全部新答案可识别，也不证明设备业务完成。

用例维护与评测见 [工具说明](</D:/Agent Repo/my_pocket_automation/scripts/perception/README.md>)；目录边界见 [协作规则](</D:/Agent Repo/my_pocket_automation/AGENTS.md>)。
