# 开发与调试工具

统一保存开发、设备调试及离线识别工具，内部按功能组织，不再设置顶层 `tools/`。

| 目录 | 职责 |
|---|---|
| `device/` | 构建、发布、运行、采集、设备诊断与通信实现。 |
| `perception/` | 特征校准、历史特征导入、用例制作、审核展示、能力评测和失效分析。 |
| `perception/lib/` | 测试与评测共用的数据校验、拼接、投影和评分实现。 |
| `perception/tests/` | 用例工具自身的测试。 |

`requirements.txt` 是共用 Python 依赖。生产脚本测试保留在仓库顶层 `tests/`；正式真值保存在 `testdata/`；临时提案在 `.tmp/annotation/`；报告和审核图输出到 `debug-runs/<运行编号>/`。

```powershell
python scripts/device/run-daily.py --help
python scripts/test.py
python scripts/test.py --group shimen other
python scripts/perception/evaluate.py
```

设备命令与费用边界见 [项目说明](</D:/Agent Repo/my_pocket_automation/README.md>)，用例维护见 [识别工具说明](</D:/Agent Repo/my_pocket_automation/scripts/perception/README.md>)。

`test.py` 支持抓鬼、副本、师门、其他四类，可组合选择；开发只跑相关类别，合入前运行默认全量，耗时上限60秒。`test_test.py` 验证分类无遗漏、无重复，以及部分回归的数据范围。
