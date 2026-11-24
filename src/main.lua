require('TSLib')
local log = require('dfx.log')
local snapshot = require('dfx.snapshot')
local config_file = '/storage/emulated/0/TouchSprite/res/daily_config.lua'
local config = assert(loadfile(config_file))()
local ctx = require('dfx.run').new(config)
local profile = require('dfx.profile')
local ok, err = pcall(function()
    require('common.screen').init(0)
    log.write(ctx, 'start', 'version=daily_002 mode=' .. config.mode)
    profile.install(ctx)
    snapshot.capture(ctx, 'start', 'debug')
    if config.mode == 'observe' then
        require('tasks.' .. (config.task or 'dungeon') .. '.task').observe(ctx)
    else
        assert(config.mode == 'run', 'invalid mode')
        assert(config.allow_reward_claim == false, 'debug policy must forbid reward claims')
        if config.step=='launch-game' then
            local result=require('common.application').start(ctx)
            log.write(ctx,'task_result','startup status='..result.status..' reason='..result.reason)
            log.write(ctx,'summary','daily_done=false scope=application_startup')
            return
        end
        local checked,running=pcall(appIsRunning,'com.netease.mhxyhtb')
        if not checked or (running~=0 and running~=1) then
            log.write(ctx,'task_result','startup status=blocked reason=game_process_state_unknown')
            pcall(snapshot.capture,ctx,'game_process_state_unknown')
            log.write(ctx,'summary','daily_done=false reason=game_process_state_unknown')
            return
        end
        if running==0 or config.step=='daily' then
            local result=require('common.application').start(ctx,config.step=='daily')
            if result.status~='done' then
                log.write(ctx,'task_result','startup status='..result.status..' reason='..result.reason)
                log.write(ctx,'summary','daily_done=false reason='..result.reason)
                return
            end
        end
        if config.step=='select-role' then
            assert(#config.accounts==1,'select-role requires one configured role')
            ctx.account=config.accounts[1]
            assert(require('common.navigation').inspect_saved(ctx),'saved role inspection failed')
            snapshot.capture(ctx,'saved_role_identity_review','evidence')
            log.write(ctx,'task_result','identity status=done reason=home_captured_for_review')
            log.write(ctx,'summary','daily_done=false scope=identity_review')
            return
        end
        if config.step=='daily' and config.tasks then
            require('daily').run(ctx)
            return
        end
        local dungeon_done = false
        local placeholders = {}
        for _, account in ipairs(config.accounts) do
            ctx.account = account
            ctx.identity_verified = false
            log.write(ctx, 'account', account.alias)
            if config.verify_role then
                local ghost=config.task=='zhuagui'
                local shimen=config.task=='shimen'
                local state=require(shimen and 'tasks.shimen.pages' or ghost and 'tasks.zhuagui.pages' or 'tasks.dungeon.pages').state()
                local active=config.task~='rewards' and (ghost and ({battle=true,go=true,depart=true,dialogue=true,find=true,retry=true,puzzle=true,puzzle_retry=true})[state]
                    or not ghost and (state=='battle' or state=='loading' or state==(config.dungeon or 'wuji')..'_active')
                )
                if shimen then
                    active=state~='unknown' and state~='home' and state~='task_list' and
                        state~='ready' and state~='completed_card'
                end
                local recovery=config.step=='complete' or ((ghost or shimen) and (config.step=='browse' or config.step=='advance'))
                if recovery and active then
                    log.write(ctx,'screen_resume','task='..config.task..' state='..state..' identity_unverified_no_new_accept_or_reward_claim')
                elseif not require('common.navigation').prepare_recorded(ctx) then
                    log.write(ctx,'task_result','account status=blocked reason=saved_role_not_ready')
                    log.write(ctx,'summary','daily_done=false reason=account_blocked')
                    return
                end
            end
            if config.step == 'daily' and not require('common.navigation').prepare_recorded(ctx) then
                log.write(ctx, 'task_result', 'account status=blocked reason=saved_role_not_ready')
                log.write(ctx, 'summary', 'daily_done=false reason=account_blocked')
                return
            end
            local task_names = config.step=='daily' and {'shimen', 'zhuagui', 'dungeon', 'rewards'} or {config.task or 'dungeon'}
            local last_task,last_status
            for _, name in ipairs(task_names) do
                log.write(ctx,'task_start',name)
                local result = require('tasks.' .. name .. '.task').run(ctx)
                last_task,last_status=name,result.status
                log.write(ctx, 'task_result', name .. ' status=' .. result.status .. ' reason=' .. (result.reason or ''))
                if name=='dungeon' then dungeon_done=result.status=='done' end
                if result.status=='not_implemented' then placeholders[#placeholders+1]=name end
                if result.status == 'failed' or result.status == 'blocked' or result.status=='paused' then
                    log.write(ctx, 'summary', 'daily_done=false reason=' .. name .. '_' .. result.status)
                    return
                end
            end
            if config.step=='daily' then
                if not require('common.navigation').finish_account(ctx) then
                    log.write(ctx,'task_result','navigation status=blocked reason=return_home_not_verified')
                    log.write(ctx,'summary','daily_done=false reason=return_home_not_verified')
                    return
                end
                if last_status=='done' then
                    log.write(ctx,'home_verified','account='..account.alias..' task='..last_task)
                end
            end
        end
        local missing=#placeholders>0 and table.concat(placeholders,',') or 'none'
        log.write(ctx,'summary','scope=' .. (config.step=='daily' and 'daily' or (config.task or 'dungeon')) ..
            ' dungeon_done=' .. tostring(dungeon_done) .. ' daily_done=false placeholders=' .. missing)
    end
end)
-- A single-step exit or exception may precede game delivery confirmation.
if ctx.recognition_materials then
    pcall(function() require('dfx.materials').keep(ctx,ok and 'delivery_not_verified' or 'script_failed') end)
end
if not ok then
    -- One diagnostic failure must not prevent the other channel or final record.
    local error_logged = pcall(log.write, ctx, 'failed', tostring(err))
    if not error_logged then pcall(nLog, '[daily][' .. ctx.run_id .. '][failed] ' .. tostring(err)) end
    pcall(snapshot.capture, ctx, 'failure')
end
pcall(profile.flush,ctx)
local finished_ok = pcall(log.write, ctx, 'finished', ok and 'script_exited_normally' or 'script_failed')
if not finished_ok then pcall(nLog, '[daily][' .. ctx.run_id .. '][finished] diagnostic_log_unavailable') end
