local M = {}
-- Events outside this list are DEBUG; preserve the result format used by the runner.
local info={start=true,account=true,account_verified=true,roster_verified=true,task_start=true,
    application_start=true,application_ready=true,home_verified=true,
    task_result=true,dungeon_scope=true,dungeon_result=true,account_result=true,summary=true,finished=true,
    screen_resume=true,entry_recovery=true,dungeon_recovery=true,find_retry_pending=true,
    find_retry=true,puzzle_retry=true,shimen_completed=true,zhuagui_completed=true,
    dungeon_completion_audit=true,dungeon_reward_claimed=true,rewards_complete=true,
    shimen_observe=true,zhuagui_observe=true,dungeon_observe=true,rewards_observe=true,
    catalog_round=true,catalog_round_done=true,catalog_cycle_done=true,
    find_collection=true,find_collection_done=true,evidence_screenshot=true,recognition_materials=true}
local errors={failed=true,error=true,error_screenshot=true,annotation_required=true,
    account_blocked=true,roster_blocked=true,list_scan_blocked=true,resume_not_verified=true}
function M.write(ctx, event, detail)
    if not info[event] and not errors[event] and event~='profile' and
        (not ctx.config or ctx.config.verbose_logs~=true) then return end
    local timing=ctx.profile and ctx.profile.clock and string.format('[elapsed_ms=%.0f]',ctx.profile.clock()-ctx.profile.started) or ''
    local line = string.format('[daily][%s]%s[%s] %s', ctx.run_id, timing, event, tostring(detail or ''))
    nLog(line)
    local path=ctx.log_path
    if errors[event] then
        path=ctx.error_path or ctx.log_path:gsub('%.log$','_error.log')
    elseif event=='profile' then path=ctx.profile_path or ctx.log_path:gsub('%.log$','_profile.log') end
    local file = assert(io.open(path, 'a'))
    file:write(line .. '\n')
    file:close()
end
return M
