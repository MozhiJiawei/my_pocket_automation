# 测试输入与真值

按任务保存稳定截图、SHA256、来源、语义标注、识别预期和审核依据。测试与评测只读本目录；算法预测不能改写答案。

- `<任务>/cases.json`：单帧真值、预期及标注历史。
- `zhuagui/rounds.json`：经用户批准的整轮多答案集合和原图坐标映射。
- `<任务>/images/`：脱敏原始画面及明确标记的合成样本。
- `zhuagui/annotation-history/`：黄金、酒类更正依据及题目图形审核记录。
- `zhuagui/sequences.json`：画面变化回放场景。
- `zhuagui/coverage.json`：题目采集覆盖与缺口。
- `regression_baseline.json`：旧算法实际通过的断言及来源报告哈希。

待审核或未采齐字段显式保留状态，不视为正确、错误或不存在。更改正式答案须有明确审核依据，保留历史；原图和已审核事实不因算法失败而删除。

审核工作数据位于 `.tmp/annotation/`；制作与更新入口见 [工具说明](</D:/Agent Repo/my_pocket_automation/scripts/perception/README.md>)。
