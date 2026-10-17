local log = require('dfx.log')
local M = {}
function M.capture(ctx, label, kind)
    kind=kind or 'error'
    assert(kind=='debug' or kind=='error' or kind=='evidence' or kind=='buffer','invalid snapshot kind')
    if kind=='debug' and (not ctx.config or ctx.config.routine_screenshots~=true) then return end
    assert(label:match('^[%w_-]+$'), 'invalid snapshot label')
    ctx.sequence = ctx.sequence + 1
    local w, h = require('common.screen').size()
    local path = string.format('%s/daily_%s_%03d_%s%s.png', ctx.screenshot_dir, ctx.run_id, ctx.sequence,
        kind=='buffer' and 'pending_' or '',label)
    snapshot(path, 0, 0, w - 1, h - 1)
    local file = assert(io.open(path, 'rb'))
    assert(file:seek('end') > 0, 'empty snapshot')
    file:close()
    if kind=='buffer' then return path end
    local event=kind=='debug' and 'screenshot' or kind=='evidence' and 'evidence_screenshot' or 'error_screenshot'
    log.write(ctx,event,path)
    return path
end
function M.retain(ctx,path)
    local prefix=ctx.screenshot_dir..'/daily_'..ctx.run_id..'_'
    assert(path:sub(1,#prefix)==prefix,'foreign evidence path')
    local final,count=path:gsub('_(%d+)_pending_','_%1_',1)
    assert(count==1,'not a buffered snapshot')
    assert(os.rename(path,final),'evidence promotion failed')
    log.write(ctx,'evidence_screenshot',final)
    return final
end
return M
