local M = {}
local function wall_ms()
    local file=io.open('/proc/uptime','r')
    if file then
        local value=tonumber((file:read('*l') or ''):match('^[%d.]+'))
        file:close()
        if value then return value*1000 end
    end
    return os.time()*1000
end
function M.install(ctx)
    if not ctx.config.profile then return end
    ctx.profile={started=wall_ms(),stats={},clock=wall_ms}
    for _,spec in ipairs({
        {'common.detector','find','recognition'},
        {'tasks.zhuagui.pages','state','state.zhuagui'},
        {'tasks.dungeon.pages','state','state.dungeon'},
        {'tasks.shimen.pages','state','state.shimen'},
        {'tasks.rewards.pages','state','state.rewards'},
        {'tasks.zhuagui.find','solve','find.solve'},
        {'tasks.zhuagui.puzzle','solve','puzzle.solve'},
        {'tasks.shimen.find','solve','find.shimen'},
        {'tasks.shimen.puzzle','solve','puzzle.shimen'},
        {'common.device','tap','input.tap'},
        {'common.device','swipe','input.swipe'},
        {'common.navigation','prepare_recorded','navigation.identity'},
        {'common.list_navigation','find','navigation.list'},
        {'tasks.zhuagui.task','run','task.zhuagui'},
        {'tasks.dungeon.task','run','task.dungeon'},
        {'tasks.shimen.task','run','task.shimen'},
        {'tasks.rewards.task','run','task.rewards'},
    }) do
        local module=require(spec[1])
        local original=module[spec[2]]
        -- Leaf recognition/state calls can run thousands of times per question.
        -- Never read /proc or build a scope key in their inner loop.
        local cpu_only=spec[3]=='recognition' or spec[3]:match('^state%.')~=nil
        local previous_alias,stat
        module[spec[2]]=function(...)
            local alias=ctx.account and ctx.account.alias or 'none'
            if alias~=previous_alias then
                local key=alias..':'..spec[3]
                stat=ctx.profile.stats[key] or {count=0,wall_ms=0,cpu_ms=0,max_ms=0,errors=0,cpu_only=cpu_only}
                ctx.profile.stats[key]=stat
                previous_alias=alias
            end
            local started,cpu=not cpu_only and wall_ms(),os.clock()
            local values=table.pack(pcall(original,...))
            local cpu_duration=(os.clock()-cpu)*1000
            local duration=cpu_only and cpu_duration or math.max(0,wall_ms()-started)
            stat.count=stat.count+1
            stat.wall_ms=stat.wall_ms+duration
            stat.cpu_ms=stat.cpu_ms+cpu_duration
            stat.max_ms=math.max(stat.max_ms,duration)
            if not values[1] then stat.errors=stat.errors+1;error(values[2],0) end
            return table.unpack(values,2,values.n)
        end
    end
end
function M.flush(ctx)
    if not ctx.profile then return end
    local log=require('dfx.log')
    log.write(ctx,'profile',string.format('scope=run wall_ms=%.0f clock=proc_uptime_or_seconds',wall_ms()-ctx.profile.started))
    local keys={};for key in pairs(ctx.profile.stats) do keys[#keys+1]=key end;table.sort(keys)
    for _,key in ipairs(keys) do
        local s=ctx.profile.stats[key]
        if s.cpu_only then
            log.write(ctx,'profile',string.format('scope=%s count=%d cpu_ms=%.3f max_cpu_ms=%.3f errors=%d',
                key,s.count,s.cpu_ms,s.max_ms,s.errors))
        else
            log.write(ctx,'profile',string.format('scope=%s count=%d wall_ms=%.0f cpu_ms=%.3f max_ms=%.0f errors=%d',
                key,s.count,s.wall_ms,s.cpu_ms,s.max_ms,s.errors))
        end
    end
end
return M
