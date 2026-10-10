# 识别开发与用例维护工具

`lib/` 共用数据读取、投影、拼接和评分实现；工具自身测试位于 `tests/` 子目录。正式输入在仓库顶层 `testdata/`，可编辑提案在 `.tmp/annotation/`，审核图和报告输出到 `debug-runs/<运行编号>/`。

旧采集、索引、特征校准、历史特征导入与断点展示入口也在本目录；设备构建、发布、运行和采集入口位于 `scripts/device/`。

目标：保存游戏画面中的事实及识别预期，让算法可以离线迭代，并在游戏改版后定位失效原因。设备运行结果与电脑识别评测分开验收。



## 用例契约

`cases.json` 保存单帧真值及预期；`corpus/zhuagui/rounds.json` 保存经用户审核的整轮答案集合、原图来源和位置映射。整轮位置由 `approve_rounds.py` 投影到原帧，不能手工独立修改两份坐标。每个用例有稳定 ID、任务内图片路径、SHA256、尺寸、采集组、数据用途、来源和保留区域。游戏版本未知时保存 `null`，不推测版本。

`truth` 保存语义事实，各字段独立记录 `value/status/source`：

- `page`：页面类型。`not_find` 只声明不是寻物页。
- `question`：题目原文与目标语义。不保存 `legacy` 等算法策略名。
- `count`：可观察到的次数；明确遮挡时为 `unknown`。
- `target_regions`：本帧已确认答案的可点击区域，坐标为原图像素，右下边界不包含。
- `target_regions_complete`：是否已穷举本帧答案；当前整轮投影为 `false`，不把截图缺口或未确认外观当作负例。
- `negative_regions`：用户明确排除的区域，如黄金题中的矿石。其他未框选区域不自动加入负例。
- `objects`：已审核的物品身份与位置，允许出现在其他题目的干扰项中。

`expected.checks` 指定这张画面需要验证什么。`forbidden_page`、`forbidden_actions` 保存明确的拒绝预期。识别结果不能修改这些预期。

`reviewed` 是有来源的独立画面审核；`user_verified`、`device_verified` 分别表示用户确认和设备结果支持。`proposed` 是提案，`pending` 是未标注。后两者必须报告为 **unscored**，不能算通过，也不能当成目标不存在。确认点击区域不代表已穷举画面中所有正确物品。

`images/catalog/manifest.json` 仅保存原采集索引；其中机器生成的可见性和整题答案验证标记不再直接作为帧级真值。重复图片合并为一个用例，来源列表完整保留。合成遮挡、缩放用例单独标记并保留父用例，不能算真实采集覆盖。

## 运行和诊断

```powershell
python -m unittest discover -s tests
python -m unittest discover -s scripts/perception/tests -t .
python scripts/perception/evaluate.py
python scripts/perception/evaluate.py --task zhuagui
python scripts/perception/evaluate.py --case <用例ID> --baseline <上次results.json的绝对路径>
```

评测只执行仓库内实际 Lua；不连接设备、网络或读取授权信息。结果默认保存在独立的 `debug-runs/<运行编号>/offline-evaluation/`。报告包含代码哈希、数据哈希、匹配后端、逐帧预期与实际、动作计划、匹配轨迹、分目标及采集组的统计。失败时输出真值绿框、明确负例蓝框和计划点击红点。基线比较区分新检查、标注变化、回归与修复，不能把修改答案当成算法修复。

整轮有多个正确答案时，选中任一个即可通过该轮的选择检查；同时列出选中／尚未选中的答案实例。生产求解器只选一个目标，未选中其余物品不能当作检测召回率。原始帧未全部纳入当前评测时不评整轮；原始采集本身可能不完整，轮次结果仍只覆盖已采画面。没有已标答案的轮次保持 `unscored`。

单帧有已标答案却没有点击计划，记为能力失败；点击明确非答案区域也失败。点击未标区域、且真值不完整时记为 `unscored`，不猜它对错。报告保留求解器拒绝／未匹配原因和失败现场。测试方法通过只说明数据契约与旧回归没有破坏，不代表新答案全部可识别；`evaluate.py` 的完整能力评测有失败时返回非零。`corpus/regression_baseline.json` 固定旧评测实际通过的断言及报告哈希，不能因人工确认答案就声称算法曾通过。新增答案检查完整进入能力报告。

当前生产代码识别的是题目目标类别，原文仍保存，但不声明评测了完整 OCR 文本。位置评测记录真实求解代码准备点击的位置，不虚构游戏点击后的成功状态。真实画面回放检查截图前后目标消失和移动；不是完整游戏模拟器。

电脑颜色后端保留历史每通道容差 25，记录 `degree` 但不声称模拟了它的准确含义。离线通过不能替代触动设备的匹配和任务完成验证。

## 新画面与标注闭环

1. 通过现有 DFX 保存断点，按任务导入脱敏画面；默认所有字段待标注。
2. AI 按同一采集轮次读取全部已采页面，提出全部可接受答案的候选区域，保留题干、其他候选和不确定性，再提供任务长图供用户审核。答案集合支持多个物品；单个图标识别不代表整题标注完整。审核不会自动推广到不同布局。
3. 确认真值，固定图片和来源；修改算法后重跑同一批数据，检查错误与正确暂停。
4. 保留旧画面，新版画面追加新用例；同时比较旧版回归与新版适配。

单帧导入示例：

```powershell
python scripts/perception/import_frame.py --task zhuagui --source 'D:/Agent Repo/my_pocket_automation/debug-runs/<运行编号>/res/<图片>.png' --group <采集组> --retain 15,174,887,1435
```

批量采集仍使用 `index-zhuagui-catalog.py` 和 `freeze-zhuagui-catalog.py`。新增证据进入权威用例时标为待审核，不覆盖原有确认值。`annotate.py` 仅用于用户明确审核的提案，须记录审核人和证据；跨题物品确认不会自动补齐题目覆盖。

数据按采集组划分用途，禁止同组跨 calibration/holdout。现有历史样本均曾用于开发或回归，标为 calibration，不冒充未见验收集；新单帧导入默认为 holdout，同组已有用途时必须沿用。用过验收集调参后应改为 calibration。

现有抓鬼提案见 [审核清单](</D:/Agent Repo/my_pocket_automation/debug-runs/20261010_174000/annotation-review/README.md>)。题目覆盖、位置标注覆盖与设备成功次数分别统计，不能用测试方法数量代替能力覆盖。

整轮审核入口见 [任务长图](</D:/Agent Repo/my_pocket_automation/debug-runs/20261010_174000/annotation-review/tasks/README.md>)，用 `python scripts/perception/render_task_review.py` 从原图和独立审核提案重新生成，或用 `--topic 兵器` 更新一类。按“类别 → 多轮差异输入 → 每轮答案集合”组织，不能选一个代表图代替整个类别，也不限制类别的正确物品种类数。

同轮列表按内容对齐，合并滑动重叠与到底后的重复截图，优先选完整可见的行消除裁剪边缘；原截图、哈希、原坐标映射和对齐误差保留。无法可靠对齐的片段不强行合并。截图张数不是独立页面数，不能据此宣称采集完整。`collection_status` 表示已采范围，`answer_set.exhaustive` 表示正确答案集合是否完成审核，两者独立；未框选位置不等于负例。模型和审核提案分别保存在 `.tmp/annotation/zhuagui/tasks/rounds.json` 和 `.tmp/annotation/zhuagui/tasks/round_annotations.json`，批准后才能进入正式真值。

长图绿框是已获用户批准的位置，橙框是 AI 答案提案，青框是待确认候选；类别索引列出每轮数量，轮次文档链接原始截图。零提案不表示该题真值为空。无法对齐的采集缺口会直接标在长图中，缺口后的行号仅用于图内定位。

本批已批准 71 轮、129 个答案实例。`approve_rounds.py --reviewer user --evidence '<明确的审核依据>'` 冻结整轮集合并投影到所有完整可见的原始帧；须已有用户审核，不能由算法自动批准。黄金矿石作为明确负例保存；更正标注时重建投影并保留历史，不累加被撤销的旧位置。题目覆盖缺口与百味酒具体外观待确认仍保留。
