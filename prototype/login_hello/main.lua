-- 口袋版自动登录原型：第 1 步
-- 目标：验证触动精灵可以加载新脚本，并启动梦幻西游口袋版。
-- 本目录与仓库中的旧脚本完全独立。

require("TSLib")

local APP_ID = "com.netease.mhxyhtb"
local SCRIPT_VERSION = "hello_world_004"
-- 当前 MuMu 设备信息确认的绝对路径；不要改成相对路径。
local SCREENSHOT_DIR = "/storage/emulated/0/TouchSprite/res"
local LOG_DIR = "/storage/emulated/0/TouchSprite/log"
local RUN_ID = os.date("%Y%m%d_%H%M%S")
local LOG_PATH = LOG_DIR .. "/hello_world_" .. RUN_ID .. ".log"

local function log(message)
    local line = "[hello_world][run=" .. RUN_ID .. "] " .. message
    nLog(line)
    local file, err = io.open(LOG_PATH, "a")
    if not file then
        nLog("[hello_world] log_open_failed=" .. LOG_PATH .. ": " .. tostring(err))
        return
    end
    local ok, writeErr = file:write(line .. "\n")
    file:close()
    if not ok then
        nLog("[hello_world] log_write_failed=" .. tostring(writeErr))
    end
end

local function capture(label)
    local width, height = getScreenSize()
    local path = SCREENSHOT_DIR .. "/hello_world_" .. RUN_ID .. "_" .. label .. ".png"
    local ok, err = pcall(function()
        snapshot(path, 0, 0, width - 1, height - 1)
        local file, openErr = io.open(path, "rb")
        if not file then error(tostring(openErr)) end
        local size = file:seek("end")
        file:close()
        if not size or size == 0 then error("screenshot is empty") end
    end)
    if ok then
        log("screenshot=" .. path)
    else
        log("screenshot_failed=" .. path .. ": " .. tostring(err))
    end
end

init(0)

log("version=" .. SCRIPT_VERSION)
log("log_path=" .. LOG_PATH)
log("screenshot_dir=" .. SCREENSHOT_DIR)
local width, height = getScreenSize()
log("screen=" .. tostring(width) .. "x" .. tostring(height))
log("Hello World：新登录原型已启动")
capture("01_start")

if appIsRunning(APP_ID) == 0 then
    log("正在启动口袋版")
    runApp(APP_ID)
    mSleep(8000)
    capture("02_after_launch")
else
    log("口袋版已经在运行")
    capture("02_already_running")
end

if appIsRunning(APP_ID) == 1 then
    log("口袋版进程已确认")
    log("result=success stage=app_process_confirmed")
else
    log("app_not_running=" .. APP_ID)
    capture("03_launch_failed")
    log("result=failure stage=app_launch reason=app_not_running")
end
log("script_finished")
