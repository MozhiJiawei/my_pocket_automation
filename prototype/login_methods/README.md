# 登录定位实验

main.lua 是独立触动精灵定位实验，不作为正式任务入口。设备操作由 Lua 执行；正式任务使用 scripts/device/run-daily.py 构建和运行 src/main.lua。

boundary.py 与 image_models.py 只读取本地截图，比较坐标、颜色、模板和 OCR 在图像变换下的定位行为，不连接或操作设备。资源在 assets/，配置为 calibration.json，依赖见 requirements.txt。测量和历史结论保存在 debug-runs/。

运行截图实验：python prototype/login_methods/boundary.py --input <本地截图绝对路径>。
