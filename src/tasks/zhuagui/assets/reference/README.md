# 酒类外观参考

这些裁图用于确定物品语义，不直接作为设备点击模板。实际特征从口袋版原始截图校准，点击后仍须验证寻物页退出与任务完成。

|物品|题目线索|外观|参考图|
|---|---|---|---|
|蛇胆酒|蛇胆泡的美酒|金色器身、灰色飘带|[snake_wine.png](snake_wine.png)|
|珍露酒|露水酿成的酒|棕灰色器身、青色飘带|[dew_wine.png](dew_wine.png)|
|虎骨酒|虎骨泡的美酒|青绿色器身、金色飘带|[tiger_wine.png](tiger_wine.png)|
|梅花酒|梅花泡成的酒|金棕色器身、粉色飘带|[plum_wine.png](plum_wine.png)|
|醉生梦死|用户确认属于酒类|深棕坛身、浅色封口布、红色酒字贴；可旋转|[用户指认图（左）](wine_user_review.png)|
|女儿红|用户确认属于酒类|金棕坛身、红色封口布、红色酒字贴；可旋转|[用户指认图（右）](wine_user_review.png)|
|百味酒|用户确认属于酒类|具体图标尚未确认，不根据名字猜外观|待补具名外观证据|

来源：[电脑版烹饪摊位具名截图](https://ol.3dmgame.com/gl/223789.html)（蛇胆、珍露、梅花）、[虎骨酒具名提示框](https://www.sohu.com/a/198082726_99983688)。抓鬼寻物图标有旋转变体；电脑版外观对应关系仅为识别参考，口袋版实测结论见任务报告。

2026-10-10 已用用户标注和口袋版完成结果确认蛇胆酒。其余三种尚未完成口袋版点击验证。不要把酒类外观猜成药瓶，也不要将某一种酒的特征用于所有酒类题目。

酒类集合为虎骨酒、女儿红、珍露酒、梅花酒、百味酒、蛇胆酒、醉生梦死。用户指认的酒坛外观见 [用户指认图](</D:/Agent Repo/my_pocket_automation/src/tasks/zhuagui/assets/reference/wine_user_review.png>)；已确认位置保存在各轮 `答案.json`，审核过程和依据保存在 `debug-runs/`。七类清单完整不等于七类外观已全部确认，也不等于设备求解器已支持七类。

## 免费重试对话校准

[retry_dialogue.png](</D:/Agent Repo/my_pocket_automation/src/tasks/zhuagui/assets/reference/retry_dialogue.png>) 是 `scripts/perception/calibrate-puzzles.py` 使用的生产校准原图，用于提取免费继续提示和按钮特征。它不作为已确认拼图答案，也不代表设备成功验收。
