local log = require('dfx.log')
local M = {}
function M.capture(ctx, label)
    assert(label:match('^[%w_-]+$'), 'invalid snapshot label')
    ctx.sequence = ctx.sequence + 1
    local w, h = require('common.screen').size()
    local path = string.format('%s/daily_%s_%03d_%s.png', ctx.screenshot_dir, ctx.run_id, ctx.sequence, label)
    snapshot(path, 0, 0, w - 1, h - 1)
    local file = assert(io.open(path, 'rb'))
    assert(file:seek('end') > 0, 'empty snapshot')
    file:close()
    log.write(ctx, 'screenshot', path)
    return path
end
return M
