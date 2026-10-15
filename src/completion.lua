-- Durable daily booleans only. Never serialize task stages, counters or retries.
local M={}
local stages={shimen='completion_card_verified',zhuagui='completion_card_verified',
    wuji='reward_claimed',chechi='reward_claimed',rewards='daily_inventory_empty'}
local function valid(ctx)
    return ctx.config and ctx.config.completion_ledger_path and ctx.account and
        ctx.account.identity_binding and ctx.account.identity_binding~='' and ctx.identity_verified and
        ctx.config.business_date==os.date('%Y%m%d')
end
local function key(ctx,task)
    return ctx.config.business_date..'\t'..ctx.account.alias..'\t'..ctx.account.identity_binding..'\t'..task
end
local function load(ctx)
    if ctx.completions then return ctx.completions end
    local records={}
    local file=io.open(ctx.config.completion_ledger_path,'r')
    if file then
        for line in file:lines() do
            local date,alias,binding,task=line:match('^(%d+)\t([%w_-]+)\t([%w]+)\t([%w]+)\ttrue$')
            if date==ctx.config.business_date and stages[task] then
                records[date..'\t'..alias..'\t'..binding..'\t'..task]=true
            end
        end
        file:close()
    end
    ctx.completions=records
    return records
end
function M.read(ctx,task)
    if not stages[task] or not valid(ctx) or not load(ctx)[key(ctx,task)] then return nil end
    return {status='done',stage=stages[task],business_date=ctx.config.business_date,completion_ledger=true}
end
function M.write(ctx,task,status,stage)
    if not stages[task] or not valid(ctx) or status~='done' or stages[task]~=stage then return end
    local records=load(ctx)
    local id=key(ctx,task)
    if records[id] then return end
    records[id]=true
    -- New daily work invalidates the old empty-inventory observation.
    if task~='rewards' then records[key(ctx,'rewards')]=nil end
    local lines={}
    for record in pairs(records) do lines[#lines+1]=record..'\ttrue\n' end
    table.sort(lines)
    local path=ctx.config.completion_ledger_path
    local file=assert(io.open(path..'.pending','w'),'completion ledger unavailable')
    assert(file:write(table.concat(lines)))
    assert(file:close())
    assert(os.rename(path..'.pending',path),'completion ledger commit failed')
end
return M
