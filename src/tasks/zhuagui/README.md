# 抓鬼

已实测野鬼、马面、僵尸、蛇胆酒、骷髅怪寻物及战斗。第 19 次保留未完成，当前只采集题目，不选择候选。题目数据覆盖 10/14，缺黄纸、香、蜡烛、牛头，见 [数据清单](../../../testdata/zhuagui/README.md)。最新次数、费用与能力边界见 [实测报告](../../../docs/ZHUAGUI_TEST_REPORT.md)。

## 流程与资源

`task.lua` 管理接取、前往、对话、寻物、战斗等待、完成确认和继续；`pages.lua` 判断当前页面；`find.lua` 先识别题目类别，再遍历该类别图标，在有限滚动范围内寻找；`counter.lua` 读取次数。识别资源全部放在本任务的 `assets/`。

旧版寻物数据已完整继承：13 组题目特征、113 组物品特征，包含旧版未命名兜底；另保留 7 类拼图的 28 组图块及原始槽位。`assets/legacy.lua` 可由 `scripts/perception/import-zhuagui-legacy.py` 重现，来源和许可见 `参考代码/`。未命名兜底不用于未知题目乱选；拼图槽位尚未在新版界面验证，不执行放置。

匹配优先使用实测的新特征，再尝试旧特征。`legacy.lua` 把旧 480×800 图标偏移统一缩放为 1.875、2.0、1.75 三档，在新版候选区域搜索，保留旧颜色与相似度；文字特征另尝试字体尺寸与新版前景颜色适配。新图标尝试四种旋转。旧酒特征未命中，新蛇胆特征已实测成功；其他酒的网上具名裁图只作语义参考，见 [酒类参考](assets/reference/README.md)。

**页面的 N/25 不等于完成 N 次。** 新任务接取后次数就增加；只有返回未进行任务的页面、次数与本地记录一致，才能记为完成。数字样本为 0–9，两位数 10 已实测，无法可靠读取时暂停。

## 运行与恢复

```powershell
# 默认观察；不接任务
python scripts/device/run-daily.py --device emulator-5562 --task zhuagui --mode observe
# 继续已有任务，完成一项就停，不接下一项
python scripts/device/run-daily.py --device emulator-5562 --task zhuagui --mode run --step advance --zhuagui-budget 75
# 在授权的日内预算内继续，遇到未适配画面停止
python scripts/device/run-daily.py --device emulator-5562 --task zhuagui --mode run --step complete --zhuagui-budget 75
```

预算默认 0，只接受 0–75 中 3 的倍数。接取前核对角色，并先持久化预留 3 精力；已有任务只续跑，不重复领取。设备进度分别保存 `attempts`（已预留接取）、`completed_count`（已验证完成）、`reserved_energy`（费用上限占用），失败重启不清零。预留不代表已扣费。

主页任务入口在有未完成任务时可能直接打开 NPC 对话。恢复按画面和所属记录判断，不强求先出现任务列表。战斗只等待；找物品点击后必须确认找物品页面退出，未成功不重复点。找物品每页保存截图，滚动保留足够重叠，避免图标始终只露半边。

识别断点可用 `--step browse` 只采集候选，不选物品；再执行 `python scripts/perception/prepare-zhuagui-breakpoint.py --run-id <运行编号>` 生成带页码的截图总览和原图索引。用户标注后从对应原图校准，复测点击结果。

批量只采集使用 `--step browse --browse-rounds 20 --zhuagui-budget 0`：只重试已有任务和滚动，每题采集七页，不调用寻物选择器。`index-zhuagui-catalog.py` 按题干建索引，人工核对后用 `freeze-zhuagui-catalog.py` 固化脱敏样本。重复题目不增加覆盖数；不完整页和到时负样本保留，但不能冒充有效题目。运行次数和测试通过都不能替代缺项清单。

仍禁止副本领奖和开启葫芦。当前只验证一个角色、900×1600 布局；游戏日界线、跨日恢复、多角色和完成 25 次后衔接下一类任务仍待验收。
