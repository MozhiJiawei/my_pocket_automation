local M = {}
local function path(ctx, task, business_date)
    assert(ctx.account.alias:match('^[%w_-]+$'), 'invalid local account alias')
    assert(task:match('^[%w_-]+$'), 'invalid task id')
    local date=business_date or ctx.config.business_date or os.date('%Y%m%d')
    assert(type(date)=='string' and date:match('^%d%d%d%d%d%d%d%d$'),'invalid business date')
    return string.format('/storage/emulated/0/TouchSprite/res/daily_progress_%s_%s_%s.lua',
        date, ctx.account.alias, task)
end
function M.read(ctx, task, business_date)
    local file = io.open(path(ctx, task, business_date), 'r')
    if not file then return nil end
    file:close()
    return assert(loadfile(path(ctx, task, business_date)))()
end
function M.write(ctx, task, status, stage, counters, business_date)
    local target = path(ctx, task, business_date)
    local file = assert(io.open(target .. '.pending', 'w'))
    local extra=''
    for _,key in ipairs({'attempts','reserved_energy','completed_count','reward_cost_reserved','find_retries','find_retry_pending','find_attempts','puzzle_retries',
        'carryover_pending','carryover_source_date','carryover_source_attempt'}) do
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
