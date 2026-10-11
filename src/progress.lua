local M = {}
local function path(ctx, task)
    assert(ctx.account.alias:match('^[%w_-]+$'), 'invalid local account alias')
    assert(task:match('^[%w_-]+$'), 'invalid task id')
    return string.format('/storage/emulated/0/TouchSprite/res/daily_progress_%s_%s_%s.lua',
        ctx.config.business_date or os.date('%Y%m%d'), ctx.account.alias, task)
end
function M.read(ctx, task)
    local file = io.open(path(ctx, task), 'r')
    if not file then return nil end
    file:close()
    return assert(loadfile(path(ctx, task)))()
end
function M.write(ctx, task, status, stage, counters)
    local target = path(ctx, task)
    local file = assert(io.open(target .. '.pending', 'w'))
    local extra=''
    for _,key in ipairs({'attempts','reserved_energy','completed_count','reward_cost_reserved','find_retries'}) do
        if counters and counters[key]~=nil then
            local value=counters[key]
            assert(type(value)=='number' and value>=0 and value%1==0,'invalid progress counter')
            extra=extra .. string.format(',%s=%d',key,value)
        end
    end
    assert(file:write(string.format('return {status=%q,stage=%q,run_id=%q%s}\n', status, stage or '', ctx.run_id,extra)))
    assert(file:close())
    assert(os.rename(target .. '.pending', target))
end
return M
