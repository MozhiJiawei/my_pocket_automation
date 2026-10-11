# 离线识别与用例维护

正式输入在 `testdata/`，提案放 `.tmp/`，审核图与评测报告输出到 `debug-runs/`。工具直接发现可读目录，不维护 case、轮次、增强或采集索引。工具自身测试位于本目录的 `tests/`。

```powershell
python scripts/test.py
python scripts/perception/evaluate.py
python scripts/perception/evaluate.py --case '抓鬼/寻物/上好的兵器/第01轮'
python scripts/perception/render_task_review.py --topic 兵器
```

`evaluate.py` 调用实际 Lua 识别代码。未审核答案及部分真值之外的点击保持未评分；明确错误、漏掉已标答案或禁止操作使测试失败。原图与增强分别统计，电脑近似找色不能证明设备业务完成。`--origin device` 只评实拍，`--baseline` 可比较此前生成的报告。

独立原图及其八种增强并行评测，原图只解码一次，增强像素直接传给识别器。成功增强图不重复编码落盘；失败增强图保存到 `.tmp/` 供报告展示。几何预期及来源仍记录在报告中，审核工具按需重建图片。可用 OpenCL GPU 批量找色，CPU 与 GPU 使用相同的整数颜色容差、图像边界和首个匹配规则。

`render_task_review.py` 按原图内容去除滚动重叠，生成带正式答案框的任务长图；拼接坐标只存在于生成过程，不作为另一份真值。`prepare-zhuagui-breakpoint.py` 展示尚未导入的设备断点。

导入一张或多张新截图，必须指定可读用例目录和公开区域；默认待审核，不覆盖已有用例：

```powershell
python scripts/perception/import_frame.py --case '抓鬼/寻物/黄纸/新界面' --source 'D:/截图/第01页.png' 'D:/截图/第02页.png' --retain 15,174,887,1435
```

AI 先查看全部输入，在 `.tmp/` 按 `答案.json` 格式准备提案。获得明确批准后应用：

```powershell
python scripts/perception/annotate.py --case '抓鬼/寻物/黄纸/新界面' --proposal 'D:/提案/答案.json' --reviewer user --evidence '用户明确确认的消息或审核依据'
```

更正替换旧答案，并在审核文字中保留先前答案。未见验证用途不会因标注而变为校准用途。待审核目录里的输入确认分类后移入对应类别，再应用批准答案。

`calibrate-*.py`、`compile-find-catalog.py` 从批准的校准画面构建设备识别资源；不读取预测建立答案，不在评测时自动重建。旧特征导入工具保留以重建历史资源。设备构建、发布、采集入口在 `scripts/device/`。
