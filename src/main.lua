require('TSLib')
local log = require('dfx.log')
local snapshot = require('dfx.snapshot')
local config_file = '/storage/emulated/0/TouchSprite/res/daily_config.lua'
local config = assert(loadfile(config_file))()
local ctx = require('dfx.run').new(config)
local ok, err = pcall(function()
    require('common.screen').init(0)
    log.write(ctx, 'start', 'version=daily_002 mode=' .. config.mode)
    snapshot.capture(ctx, 'start')
    if config.mode == 'observe' then
        require('tasks.' .. (config.task or 'dungeon') .. '.task').observe(ctx)
    else
        assert(config.mode == 'run', 'invalid mode')
        assert(config.allow_reward_claim == false, 'debug policy must forbid reward claims')
        local dungeon_done = false
        local placeholders = {}
        for _, account in ipairs(config.accounts) do
            ctx.account = account
            ctx.identity_verified = false
            log.write(ctx, 'account', account.alias)
            if config.step == 'daily' and not require('common.navigation').prepare_recorded(ctx) then
                log.write(ctx, 'task_result', 'account status=blocked reason=saved_role_not_ready')
                log.write(ctx, 'summary', 'daily_done=false reason=account_blocked')
                return
            end
            local task_names = config.step=='daily' and {'shimen', 'zhuagui', 'dungeon', 'rewards'} or {config.task or 'dungeon'}
            for _, name in ipairs(task_names) do
                local result = require('tasks.' .. name .. '.task').run(ctx)
                log.write(ctx, 'task_result', name .. ' status=' .. result.status .. ' reason=' .. (result.reason or ''))
                if name=='dungeon' then dungeon_done=result.status=='done' end
                if result.status=='not_implemented' then placeholders[#placeholders+1]=name end
                if result.status == 'failed' or result.status == 'blocked' or result.status=='paused' then
                    log.write(ctx, 'summary', 'daily_done=false reason=' .. name .. '_' .. result.status)
                    return
                end
            end
            if config.step=='daily' and not require('common.navigation').finish_account(ctx) then
                log.write(ctx,'task_result','navigation status=blocked reason=return_home_not_verified')
                log.write(ctx,'summary','daily_done=false reason=return_home_not_verified')
                return
            end
        end
        local missing=#placeholders>0 and table.concat(placeholders,',') or 'none'
        log.write(ctx,'summary','scope=' .. (config.step=='daily' and 'daily' or (config.task or 'dungeon')) ..
            ' dungeon_done=' .. tostring(dungeon_done) .. ' daily_done=false placeholders=' .. missing)
    end
end)
if not ok then
    -- One diagnostic failure must not prevent the other channel or final record.
    local error_logged = pcall(log.write, ctx, 'failed', tostring(err))
    if not error_logged then pcall(nLog, '[daily][' .. ctx.run_id .. '][failed] ' .. tostring(err)) end
    pcall(snapshot.capture, ctx, 'failure')
end
local finished_ok = pcall(log.write, ctx, 'finished', ok and 'script_exited_normally' or 'script_failed')
if not finished_ok then pcall(nLog, '[daily][' .. ctx.run_id .. '][finished] diagnostic_log_unavailable') end
