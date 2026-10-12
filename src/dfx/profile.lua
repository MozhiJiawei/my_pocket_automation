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
    ctx.profile={started=wall_ms(),stats={}}
    for _,spec in ipairs({
        {'common.detector','find','recognition'},
        {'tasks.zhuagui.pages','state','state.zhuagui'},
        {'tasks.dungeon.pages','state','state.dungeon'},
        {'tasks.zhuagui.find','solve','find.solve'},
        {'tasks.zhuagui.puzzle','solve','puzzle.solve'},
        {'common.device','tap','input.tap'},
        {'common.device','swipe','input.swipe'},
        {'common.navigation','prepare_recorded','navigation.identity'},
        {'tasks.zhuagui.task','run','task.zhuagui'},
        {'tasks.dungeon.task','run','task.dungeon'},
    }) do
        local module=require(spec[1])
        local original=module[spec[2]]
        module[spec[2]]=function(...)
            local key=(ctx.account and ctx.account.alias or 'none')..':'..spec[3]
            local started,cpu=wall_ms(),os.clock()
            local values=table.pack(pcall(original,...))
            local duration=math.max(0,wall_ms()-started)
            local stat=ctx.profile.stats[key] or {count=0,wall_ms=0,cpu_ms=0,max_ms=0,errors=0}
            ctx.profile.stats[key]=stat
            stat.count=stat.count+1
            stat.wall_ms=stat.wall_ms+duration
            stat.cpu_ms=stat.cpu_ms+(os.clock()-cpu)*1000
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
        log.write(ctx,'profile',string.format('scope=%s count=%d wall_ms=%.0f cpu_ms=%.3f max_ms=%.0f errors=%d',
            key,s.count,s.wall_ms,s.cpu_ms,s.max_ms,s.errors))
    end
end
return M
