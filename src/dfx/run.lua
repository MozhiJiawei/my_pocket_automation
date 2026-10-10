local M = {}
function M.new(config)
    local context = {config = config, run_id = config.run_id or os.date('%Y%m%d_%H%M%S'), sequence = 0}
    context.log_path = '/storage/emulated/0/TouchSprite/log/daily_' .. context.run_id .. '.log'
    context.screenshot_dir = '/storage/emulated/0/TouchSprite/res'
    return context
end
return M
