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
local function retire_carryover(ctx,record)
    if record.carryover_pending~=0 or not record.carryover_source_date then return end
    local date=string.format('%08d',record.carryover_source_date)
    if not ctx.config.business_date or date>=ctx.config.business_date then return end
    local previous=progress.read(ctx,'shimen',date)
    if previous and previous.status=='running' and previous.attempts==record.carryover_source_attempt then
        progress.write(ctx,'shimen','carried_over','delivery_carried_to_'..ctx.config.business_date,previous,date)
        log.write(ctx,'shimen_carryover_retired','source_date='..date..' source_attempt='..previous.attempts)
    end
end
function M.observe(ctx)
    log.write(ctx,'shimen_observe','state='..pages.state()..' no_actions=true')
end
local function enter(ctx)
    if not ctx.identity_verified then return stop(ctx,'role_identity_not_verified','blocked') end
    local state=pages.state()
    if state=='home' then
        if not device.tap(ctx,require('tasks.zhuagui.assets.home_tasks'),'shimen_open_tasks') or
            not device.wait(function()
                local next_state=pages.state()
                return next_state~='home' and next_state~='unknown'
            end,20) then
            return stop(ctx,'shimen_task_list_postcondition_not_verified')
        end
        state=pages.state()
    end
    if state=='task_list' then
        if not device.tap(ctx,pages.features.task_card,'shimen_open_card') or
            not device.wait(function() return pages.state()~='task_list' end,20) then
            return stop(ctx,'shimen_card_postcondition_not_verified')
        end
        state=pages.state()
    end
    if state=='unknown' or state=='home' or state=='task_list' then
        return stop(ctx,'shimen_page_requires_calibration')
    end
    log.write(ctx,'shimen_entry','state='..state..' count='..tostring(pages.count()))
    snapshot.capture(ctx,'shimen_entry_evidence','debug')
    return result('running','shimen_task_entry_verified')
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
    if ctx.config.step=='enter' then return enter(ctx) end
    local record=progress.read(ctx,'shimen')
    local step=ctx.config.step
    if record and record.status=='done' and ctx.identity_verified and
        record.attempts==20 and record.completed_count==20 and record.carryover_pending~=1 and
        ({delivery_verified=true,completion_card_verified=true,one_task_completed=true})[record.stage] and
        (step=='daily' or step=='complete') then
        return result('done','daily_done_skip')
    end
    if not record and (step=='complete' or step=='daily') then
        local state=pages.state()
        if ctx.config.shimen_resume_date then
            local previous=progress.read(ctx,'shimen',ctx.config.shimen_resume_date)
            local active=pages.actions[state] or ({find=true,puzzle=true,battle=true,loading=true})[state]
            if not previous or previous.status~='running' or not previous.attempts or previous.attempts<1 or
                not ctx.config.business_date or ctx.config.shimen_resume_date>=ctx.config.business_date or
                not active or pages.count()~=0 then
                return stop(ctx,'shimen_carryover_not_verified','blocked')
            end
            record={status='running',attempts=0,completed_count=0,reserved_energy=0,
                find_attempts=previous.find_attempts or 0,find_retry_pending=previous.find_retry_pending or 0,
                carryover_pending=1,carryover_source_date=tonumber(ctx.config.shimen_resume_date),
                carryover_source_attempt=previous.attempts}
            progress.write(ctx,'shimen','running','carryover_owned_task',record)
            log.write(ctx,'shimen_carryover','source_date='..ctx.config.shimen_resume_date..
                ' source_attempt='..previous.attempts..' current_count=0')
        elseif ctx.identity_verified and (state=='home' or state=='task_list' or state=='ready') then
            record={status='running',attempts=0,completed_count=0,reserved_energy=0}
        end
    end
    if not record or record.status~='running' then
        return stop(ctx,'shimen_active_task_ownership_missing','blocked')
    end
    retire_carryover(ctx,record)
    if step~='advance' and step~='complete' and step~='daily' then
        return stop(ctx,'shimen_step_requires_calibration')
    end
    if ctx.config.shimen_puzzle_family and pages.state()~='puzzle' then
        return stop(ctx,'shimen_puzzle_page_not_verified')
    end
    local deadline=os.time()+(ctx.config.shimen_timeout or 1800)
    local last_state,actions=nil,0
    local completion_scrolls=0
    local puzzle_attempted=record.stage=='puzzle_exit_requires_delivery_verification'
    while os.time()<deadline do
        local state=pages.state()
        if record.attempts==0 and record.carryover_pending~=1 and
            state~='home' and state~='task_list' and state~='ready' then
            return stop(ctx,'shimen_active_task_ownership_missing','blocked')
        end
        if state~=last_state then log.write(ctx,'state','shimen '..state);last_state=state end
        if state=='puzzle_retry' and puzzle_attempted then
            progress.write(ctx,'shimen','running','puzzle_failed_requires_annotation',record)
            return stop(ctx,'puzzle_game_result_not_verified')
        elseif state=='puzzle' then
            puzzle_attempted=true
            local solved,reason=require('tasks.shimen.puzzle').solve(ctx,ctx.config.shimen_puzzle_family or 'auto')
            if not solved then return stop(ctx,reason) end
            progress.write(ctx,'shimen','running','puzzle_exit_requires_delivery_verification',record)
            if step=='advance' then return result('paused','one_minigame_completed') end
        elseif state=='find' then
            local outcome=find(ctx,record)
            if outcome.reason~='one_minigame_completed' or step=='advance' then return outcome end
        elseif state=='gourd_notice' then
            if not device.wait(function() return pages.state()~='gourd_notice' end,10,500) then
                return stop(ctx,'shimen_gourd_notice_not_closed')
            end
        elseif state=='battle' or state=='loading' then
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
                if record.carryover_pending==1 then
                    if count~=0 then return stop(ctx,'shimen_carryover_count_mismatch','blocked') end
                    log.write(ctx,'shimen_carryover_completed','source_date='..record.carryover_source_date..
                        ' source_attempt='..record.carryover_source_attempt..' current_count=0')
                    snapshot.capture(ctx,'shimen_carryover_completion_evidence','debug')
                    record.carryover_pending=0
                    retire_carryover(ctx,record)
                end
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
                actions=0
                puzzle_attempted=false
            end
        elseif state=='home' then
            if not ctx.identity_verified then return stop(ctx,'role_identity_not_verified','blocked') end
            if not device.tap(ctx,require('tasks.zhuagui.assets.home_tasks'),'shimen_open_tasks') or
                not device.wait(function()
                    local next_state=pages.state()
                    return next_state~='home' and next_state~='unknown'
                end,20) then
                return stop(ctx,'shimen_task_list_postcondition_not_verified')
            end
        elseif state=='completed_card' then
            if record.attempts~=20 or ((record.completed_count or 0)~=19 and (record.completed_count or 0)~=20) then
                return stop(ctx,'shimen_completed_card_ledger_mismatch','blocked')
            end
            if not ctx.identity_verified then
                if not require('common.navigation').prepare_recorded(ctx) then
                    return stop(ctx,'role_identity_not_verified','blocked')
                end
            else
                record.completed_count=20
                progress.write(ctx,'shimen','done','completion_card_verified',record)
                log.write(ctx,'shimen_completed','count=20/20')
                snapshot.capture(ctx,'shimen_completion_evidence','debug')
                return result('done','all_twenty_tasks_completed')
            end
        elseif state=='task_list' then
            if not ctx.identity_verified then return stop(ctx,'role_identity_not_verified','blocked') end
            if record.attempts==20 and not require('common.detector').present(pages.features.task_card) then
                if completion_scrolls>=4 then return stop(ctx,'shimen_completed_card_not_found') end
                if not device.swipe(ctx,pages.features.task_list,'shimen_find_completed_card',{800,1260},{800,600}) then
                    return stop(ctx,'shimen_completion_list_changed')
                end
                completion_scrolls=completion_scrolls+1
            else
                if not device.tap(ctx,pages.features.task_card,'shimen_open_card') or
                    not device.wait(function() return pages.state()~='task_list' end,20) then
                    return stop(ctx,'shimen_card_postcondition_not_verified')
                end
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
            if state=='prepare_find' and (record.find_attempts or 0)>=FIND_ATTEMPT_LIMIT then
                return stop(ctx,'find_retry_limit_reached','blocked')
            end
            actions=actions+1
            if actions>12 then return stop(ctx,'shimen_action_limit') end
            local tapped=device.tap(ctx,pages.actions[state],'shimen_'..state)
            if not tapped then
                -- Battles can finish between observing a control and its guarded tap.
                -- Reobserve a changed page; an unchanged target still stops.
                if pages.state()==state then return stop(ctx,'shimen_action_postcondition_not_verified') end
            elseif not device.wait(function() return pages.state()~=state end,20) then
                return stop(ctx,'shimen_action_postcondition_not_verified')
            end
        elseif state=='unknown' then
            -- A control can disappear before the loading page has settled.
            -- Observe briefly without actions; persistent unknown pages still stop.
            if not device.wait(function() return pages.state()~='unknown' end,10,500) then
                return stop(ctx,'shimen_page_requires_calibration')
            end
        else
            return stop(ctx,'shimen_page_requires_calibration')
        end
        mSleep(500)
    end
    return stop(ctx,'shimen_timeout','failed')
end
return M
