# 抓鬼题目离线样本

按完整题干去重，按用户指定的 14 项检查覆盖。当前 **10/14，未采齐**；缺黄纸、香、蜡烛、牛头。泛化“酒”、兵器、骷髅怪另存，不抵扣缺项。

权威单帧数据为 [cases.json](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/cases.json>)：486 个去重真实画面用例、4 个显式合成用例。用户已批准 71 轮、129 个答案实例，冻结在 [rounds.json](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/rounds.json>)，投影覆盖 184 张原始帧；黄金矿石明确负例覆盖 17 张。采集缺口和未标区域不自动作为负例，人工确认答案不代表生产算法可识别。下面的 474 张统计保留原采集记录口径，重复图片在正式用例中合并、来源保留。

权威真值及识别预期保存在 cases.json；images/catalog/manifest.json 仅保留采集来源，不能用其机器标记生成真值。每个用例保存题目、脱敏截图、来源、SHA256。`hint_visible=false` 是倒计时结束后的负样本，不能计作有效题目。`catalog_complete` 与 `answer_verified` 分别记录候选目录是否完整、是否实测过答案，不能混用。

|题目|有效截图|状态|样本|
|---|---:|---|---|
|梅花酒|3|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/08592f0cc5f9/page_01.png>)|
|虎骨酒|2|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/50e927edacd7/page_01.png>)|
|蛇胆酒|3|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/849316ea524f/page_01.png>)|
|珍露酒|2|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/0d44c660dac4/page_01.png>)|
|黄金|73|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/56be618e9441/page_01.png>)|
|黄纸|0|待补采|—|
|书籍|108|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/1202e799fddd/page_01.png>)|
|书画|73|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/cd28b61329e8/page_01.png>)|
|香|0|待补采|—|
|蜡烛|0|待补采|—|
|野鬼|1|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/ghost_wild/page_01.png>)|
|牛头|0|待补采|—|
|马面|1|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/ghost_horse/page_01.png>)|
|僵尸|1|已采集|[题目与候选](</D:/Agent Repo/my_pocket_automation/testdata/zhuagui/images/catalog/ghost_zombie/page_01.png>)|

之前采集 31 轮，本次新增 61 轮开始记录，用户要求停止后不再补采。本次 59 轮完成页面采集、57 轮保存全部七页；418 张原始页面截图去除同轮重复画面后新增 397 张脱敏样本。总计 13 个去重题目、474 张样本，其中 468 张有效、6 张为退回 NPC 的负样本。按题干去重的用例同时保留各轮不同布局和来源；`collection_runs` 记录新增各轮题目、页数和完整性。重复导入不会重复添加已有来源。

累计 92 轮只观察到书籍、书画、黄金、兵器、泛化酒；仅点再试一次和滚动，没有选择候选或接新任务。四种具名酒及已验证找鬼截图从原始归档恢复。牛头只有旧特征，没有真实题目帧，不能算已采。精力保持 446，第 19 项未完成，葫芦未打开。黄纸等缺项下次遇到对应现场时单独收集。

题目识别回归使用实际 Lua 模块；同时检查截图脱敏、校验值、题干去重及缺项报告。测试通过不代表 14 项已全部采齐，也不代表未实测题目的候选答案已确认。

```powershell
python scripts/perception/evaluate.py --task zhuagui
```

采集入口：`run-daily.py --task zhuagui --mode run --step browse --browse-rounds 20 --zhuagui-budget 0`，需要明确设备。`index-zhuagui-catalog.py` 只读取截图、OCR 建索引；`freeze-zhuagui-catalog.py` 只将人工核对的样本固化，不发送设备输入。
