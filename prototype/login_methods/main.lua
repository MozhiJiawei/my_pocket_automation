-- Six-method experiment: native TouchSprite half of the host/device loop.
-- Configuration and screenshots use device absolute paths. No account data.
require("TSLib")
local c = assert(loadfile("/storage/emulated/0/TouchSprite/res/login_probe_config.lua"))()
local root = "/storage/emulated/0/TouchSprite"
local path = root .. "/log/hello_world_" .. c.run_id .. ".log"
local function log(s)
    local line = "[login_methods][run=" .. c.run_id .. "] " .. s
    nLog(line)
    local f = assert(io.open(path, "a"))
    f:write(line .. "\n")
    f:close()
end
local function capture(label, w, h)
    local file = root .. "/res/hello_world_" .. c.run_id .. "_" .. label .. ".png"
    snapshot(file, 0, 0, w - 1, h - 1)
    log("screenshot=" .. file)
end
local function run()
    init(1)
    local a, b = getScreenSize()
    local w, h = math.max(a, b), math.min(a, b)
    log("version=login_methods_002 method=" .. c.method)
    log("log_path=" .. path .. " screen=" .. w .. "x" .. h .. " init=1")
    capture("native_before", w, h)
    local start = os.clock()
    local x, y = -1, -1
    if c.method == "fixed" then
        if w ~= c.base_w or h ~= c.base_h then
            log("result=unsupported reason=fixed_resolution_mismatch")
            return
        end
        x, y = c.tap_x, c.tap_y
    elseif c.method == "relative" then
        x = math.floor(c.tap_x / c.base_w * w + 0.5)
        y = math.floor(c.tap_y / c.base_h * h + 0.5)
        log("edge_variant_x=" .. (w - (c.base_w - c.tap_x)) .. " edge_variant_y=" .. (h - (c.base_h - c.tap_y)))
    elseif c.method == "multicolor" then
        log("locator=multicolor degree=95 feature_points=12")
        x, y = findMultiColorInRegionFuzzy(c.anchor_color, c.offset_colors, 95,
            math.floor(w * 0.75), math.floor(h * 0.5), w - 1, h - 1)
        if x >= 0 then x, y = x + c.click_dx, y + c.click_dy end
    elseif c.method == "template" then
        log("locator=template degree=90 kind=1 binary_threshold=180")
        x, y = findImageInRegionFuzzy(c.template_path, 90,
            math.floor(w * 0.75), math.floor(h * 0.5), w - 1, h - 1, 0, 1, 180)
        if x >= 0 then x, y = x + c.template_click_dx, y + c.template_click_dy end
    else
        error("unknown_native_method")
    end
    log(string.format("located_x=%s located_y=%s locate_cpu_ms=%.3f", tostring(x), tostring(y), (os.clock() - start) * 1000))
    if x < 0 or y < 0 then
        log("result=not_found")
        return
    end
    if x < w * 0.75 or y < h * 0.5 or x >= w or y >= h then
        log("result=rejected reason=outside_entry_region")
        return
    end
    if not c.click then log("result=located dry_run=true"); return end
    touchDown(1, x, y)
    mSleep(60)
    touchUp(1, x, y)
    log("action=tap x=" .. x .. " y=" .. y)
    mSleep(1600)
    capture("native_after", w, h)
    log("result=tap_sent verification=host_required")
end
local ok, err = pcall(run)
if not ok then
    log("result=error reason=" .. tostring(err))
    local a, b = getScreenSize()
    pcall(capture, "native_failure", math.max(a, b), math.min(a, b))
end
log("script_finished")
