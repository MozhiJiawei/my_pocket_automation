local M = {}
local quiet={tap=true,swipe=true,find_search=true,find_scan=true,find_target=true,screenshot=true,
    energy_policy=true,energy_reservation=true,roster_counts=true}
function M.write(ctx, event, detail)
    if quiet[event] and (not ctx.config or ctx.config.verbose_logs~=true) then return end
    local timing=ctx.profile and ctx.profile.clock and string.format('[elapsed_ms=%.0f]',ctx.profile.clock()-ctx.profile.started) or ''
    local line = string.format('[daily][%s]%s[%s] %s', ctx.run_id, timing, event, tostring(detail or ''))
    nLog(line)
    local path=ctx.log_path
    if event=='failed' or event=='error' or event=='error_screenshot' then
        path=ctx.error_path or ctx.log_path:gsub('%.log$','_error.log')
    elseif event=='profile' then path=ctx.profile_path or ctx.log_path:gsub('%.log$','_profile.log') end
    local file = assert(io.open(path, 'a'))
    file:write(line .. '\n')
    file:close()
end
return M
