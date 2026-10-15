-- Observations and retry counters live only in this invocation.
-- Game pages remain the authority for resuming and completing tasks.
local M = {}
local function records(ctx)
    ctx.task_state = ctx.task_state or {}
    local alias = assert(ctx.account.alias, 'role alias required')
    ctx.task_state[alias] = ctx.task_state[alias] or {}
    return ctx.task_state[alias]
end
function M.read(ctx, task)
    local record=records(ctx)[task]
    if record and record.business_date~=(ctx.config and ctx.config.business_date) then return nil end
    return record
end
function M.write(ctx, task, status, stage, counters)
    local record = {status=status, stage=stage or ''}
    for key, value in pairs(counters or {}) do record[key]=value end
    record.status, record.stage = status, stage or ''
    record.business_date = ctx.config and ctx.config.business_date
    records(ctx)[task] = record
    return record
end
return M
