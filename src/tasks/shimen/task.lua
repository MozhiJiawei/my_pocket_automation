local M={}
local pages=require('tasks.shimen.pages')
local device=require('common.device')
local progress=require('progress')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local FIND_ATTEMPT_LIMIT=4 -- First attempt plus at most three free retries.
local function result(status,reason) return {status=status,reason=reason} end
local function stop(ctx,reason,status)
    snapshot.capture(ctx,reason)
    return result(status or 'paused',reason)
end
function M.observe(ctx)
    log.write(ctx,'shimen_observe','state='..pages.state()..' no_actions=true')
end
local function find(ctx,record)
    if (record.find_attempts or 0)>=FIND_ATTEMPT_LIMIT then
        return stop(ctx,'find_retry_limit_reached','blocked')
    end
    -- Interrupted solves also consume an opportunity.
    record.find_attempts=(record.find_attempts or 0)+1
    record.find_retry_pending=1
    progress.write(ctx,'shimen','running','find_attempt_reserved',record)
    log.write(ctx,'shimen_find_attempt','attempt='..record.find_attempts..'/'..FIND_ATTEMPT_LIMIT)
    local ok,reason=require('tasks.shimen.find').solve(ctx)
    if not ok then
        snapshot.capture(ctx,reason)
        progress.write(ctx,'shimen','running','find_recognition_failed',record)
        log.write(ctx,'annotation_required','task=shimen reason='..reason)
        if record.find_attempts>=FIND_ATTEMPT_LIMIT then return stop(ctx,'find_retry_limit_reached','blocked') end
        return result('paused',reason)
    end
    record.find_retry_pending=0
    progress.write(ctx,'shimen','running','find_exit_requires_delivery_verification',record)
    return result('paused','one_minigame_completed')
end
function M.run(ctx)
    if ctx.config.step=='observe' then M.observe(ctx);return result('paused','observation_only') end
    local record=progress.read(ctx,'shimen')
    if not record or record.status~='running' then
        return stop(ctx,'shimen_active_task_ownership_missing','blocked')
    end
    local step=ctx.config.step
    if step~='advance' and step~='complete' and step~='daily' then
        return stop(ctx,'shimen_step_requires_calibration')
    end
    if ctx.config.shimen_puzzle_family and pages.state()~='puzzle' then
        return stop(ctx,'shimen_puzzle_page_not_verified')
    end
    local deadline=os.time()+(ctx.config.shimen_timeout or 1800)
    local last_state,actions=nil,0
    while os.time()<deadline do
        local state=pages.state()
        if state~=last_state then log.write(ctx,'state','shimen '..state);last_state=state end
        if state=='puzzle' then
            local solved,reason=require('tasks.shimen.puzzle').solve(ctx,ctx.config.shimen_puzzle_family or 'auto')
            if not solved then return stop(ctx,reason) end
            progress.write(ctx,'shimen','running','puzzle_exit_requires_delivery_verification',record)
            if step=='advance' then return result('paused','one_minigame_completed') end
        elseif state=='find' then
            local outcome=find(ctx,record)
            if outcome.reason~='one_minigame_completed' or step=='advance' then return outcome end
        elseif state=='battle' then
            mSleep(1000)
        elseif state=='ready' then
            if not ctx.identity_verified then
                if not device.tap(ctx,pages.features.back,'shimen_return_for_identity') or
                    not device.wait(function() return pages.state()~='ready' end,20) then
                    return stop(ctx,'shimen_return_postcondition_not_verified')
                end
                if not require('common.navigation').prepare_recorded(ctx) then
                    return stop(ctx,'role_identity_not_verified','blocked')
                end
            else
                local count=pages.count()
                if count==nil or count~=record.attempts or
                    ((record.completed_count or 0)~=count-1 and (record.completed_count or 0)~=count) then
                    return stop(ctx,'shimen_completion_count_mismatch','blocked')
                end
                record.completed_count=count
                progress.write(ctx,'shimen',count==20 and 'done' or 'running','delivery_verified',record)
                log.write(ctx,'shimen_completed','count='..count..'/20')
                snapshot.capture(ctx,'shimen_completion_evidence','debug')
                if count==20 then return result('done','all_twenty_tasks_completed') end
                if step=='advance' then return result('paused','one_task_completed') end
                record.attempts=count+1
                record.reserved_energy=(record.reserved_energy or 0)+2
                record.find_attempts=0;record.find_retry_pending=0
                progress.write(ctx,'shimen','running','accept_reserved',record)
                if not device.tap(ctx,pages.features.accept,'shimen_accept') or
                    not device.wait(function() return pages.state()~='ready' and pages.count()==record.attempts end,20) then
                    return stop(ctx,'shimen_accept_postcondition_not_verified')
                end
            end
        elseif state=='home' then
            if not ctx.identity_verified then return stop(ctx,'role_identity_not_verified','blocked') end
            if not device.tap(ctx,require('tasks.zhuagui.assets.home_tasks'),'shimen_open_tasks') or
                not device.wait(function() return pages.state()=='task_list' end,20) then
                return stop(ctx,'shimen_task_list_postcondition_not_verified')
            end
        elseif state=='task_list' then
            if not ctx.identity_verified then return stop(ctx,'role_identity_not_verified','blocked') end
            if not device.tap(ctx,pages.features.task_card,'shimen_open_card') or
                not device.wait(function() return pages.state()~='task_list' end,20) then
                return stop(ctx,'shimen_card_postcondition_not_verified')
            end
        elseif state=='idle' then
            if not ctx.identity_verified then return stop(ctx,'role_identity_not_verified','blocked') end
            local count=pages.count()
            if count==nil or count~=record.attempts or (record.completed_count or 0)~=count-1 then
                return stop(ctx,'shimen_completion_count_mismatch','blocked')
            end
            record.completed_count=count
            progress.write(ctx,'shimen',count==20 and 'done' or 'paused','one_task_completed',record)
            snapshot.capture(ctx,'shimen_completion_evidence','debug')
            return result(count==20 and 'done' or 'paused','one_task_completed')
        elseif state=='retry' then
            if record.find_retry_pending~=1 then return stop(ctx,'retry_without_recognition_failure') end
            if (record.find_attempts or 0)>=FIND_ATTEMPT_LIMIT then return stop(ctx,'find_retry_limit_reached','blocked') end
            if not pages.actions.retry then return stop(ctx,'shimen_retry_requires_calibration') end
            record.find_retry_pending=0
            progress.write(ctx,'shimen','running','free_find_retry_reserved',record)
            if not device.tap(ctx,pages.actions.retry,'shimen_free_find_retry') or
                not device.wait(function() return pages.state()~='retry' end,20) then
                return stop(ctx,'shimen_retry_postcondition_not_verified')
            end
            actions=0
        elseif pages.actions[state] then
            actions=actions+1
            if actions>12 then return stop(ctx,'shimen_action_limit') end
            if not device.tap(ctx,pages.actions[state],'shimen_'..state) or
                not device.wait(function() return pages.state()~=state end,20) then
                return stop(ctx,'shimen_action_postcondition_not_verified')
            end
        else
            return stop(ctx,'shimen_page_requires_calibration')
        end
        mSleep(500)
    end
    return stop(ctx,'shimen_timeout','failed')
end
return M
