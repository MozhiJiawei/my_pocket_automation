local M={}
local pages=require('tasks.shimen.pages')
local device=require('common.device')
local progress=require('progress')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local materials=require('dfx.materials')
local list=require('common.list_navigation')
local FIND_ATTEMPT_LIMIT=4 -- First attempt plus at most three free retries.
local function result(status,reason,evidence) return {status=status,reason=reason,failure_evidence=evidence} end
local function stop(ctx,reason,status)
    materials.keep(ctx,reason)
    return result(status or 'paused',reason,snapshot.capture(ctx,reason))
end
local function open_list_card(ctx)
    local spec={name='shimen_entry_or_completed',page=pages.features.task_list,
        valid=function() local s=pages.state();return s=='task_list' or s=='completed_card' end,
        inspect=function()
            if pages.state()=='completed_card' then return {kind='completed'} end
            if pages.features.task_card and require('common.detector').present(pages.features.task_card) then
                return {kind='entry',feature=pages.features.task_card}
            end
        end}
    local match,reason=list.find(ctx,spec)
    if not match then return false,reason=='target_not_found' and 'shimen_completed_card_not_found' or 'shimen_completion_list_changed' end
    if not list.activate(ctx,spec,match,'shimen_open_card') then return false,'shimen_card_postcondition_not_verified' end
    if match.kind=='entry' and not device.wait(function() return pages.state()~='task_list' end,20) then
        return false,'shimen_card_postcondition_not_verified'
    end
    return true
end
local function audit_existing_completion(ctx)
    if not ctx.identity_verified or not ctx.config.business_date or
        ctx.config.business_date~=os.date('%Y%m%d') or pages.state()~='completed_card' then
        return stop(ctx,'shimen_existing_completion_not_verified','blocked')
    end
    snapshot.capture(ctx,'shimen_existing_completion_card','debug')
    materials.clear(ctx)
    progress.write(ctx,'shimen','done','completion_card_verified')
    log.write(ctx,'shimen_completed','completion_card=true business_date='..ctx.config.business_date)
    return result('done','completion_card_verified')
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
        local ok,reason=open_list_card(ctx)
        if not ok then return stop(ctx,reason) end
        state=pages.state()
    end
    if state=='unknown' or state=='home' or state=='task_list' then
        return stop(ctx,'shimen_page_requires_calibration')
    end
    log.write(ctx,'shimen_entry','state='..state)
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
    local prepared,prepare_reason=materials.prepare(ctx,'shimen','find')
    if not prepared then return stop(ctx,prepare_reason) end
    local ok,reason=require('tasks.shimen.find').solve(ctx)
    if not ok then
        materials.keep(ctx,reason)
        local evidence=snapshot.capture(ctx,reason)
        progress.write(ctx,'shimen','running','find_recognition_failed',record)
        log.write(ctx,'annotation_required','task=shimen reason='..reason)
        if record.find_attempts>=FIND_ATTEMPT_LIMIT then return result('blocked','find_retry_limit_reached',evidence) end
        return result('paused',reason,evidence)
    end
    record.find_retry_pending=0
    progress.write(ctx,'shimen','running','find_exit_requires_delivery_verification',record)
    return result('paused','one_minigame_completed')
end
local function browse(ctx)
    -- Only a verified free retry guarantees a fresh first screen. Never sample
    -- a current find page whose scroll position and selected items are unknown.
    if pages.state()~='retry' then return stop(ctx,'shimen_catalog_retry_required') end
    if not device.tap(ctx,pages.actions.retry,'shimen_catalog_free_retry',function()
        return pages.state()=='retry'
    end) or not device.wait(function()
        local state=pages.state()
        return state=='find' or state=='prepare_find'
    end,20) then return stop(ctx,'shimen_catalog_retry_not_verified') end
    if pages.state()=='prepare_find' then
        if not device.tap(ctx,pages.actions.prepare_find,'shimen_catalog_prepare_find',function()
            return pages.state()=='prepare_find'
        end) or not device.wait(function() return pages.state()=='find' end,20) then
            return stop(ctx,'shimen_catalog_find_not_open')
        end
    end
    log.write(ctx,'catalog_round','task=shimen target='..tostring(require('tasks.shimen.find').identify())..
        ' candidate_taps=0 new_accepts=0')
    return require('tasks.zhuagui.catalog').capture(ctx,'shimen_catalog_')
end
function M.run(ctx)
    if ctx.config.step=='observe' then M.observe(ctx);return result('paused','observation_only') end
    if ctx.config.step=='enter' then return enter(ctx) end
    if ctx.config.step=='browse' then return browse(ctx) end
    local record=progress.read(ctx,'shimen')
    local step=ctx.config.step
    local initial=pages.state()
    if initial=='completed_card' and (ctx.identity_verified or not record) then return audit_existing_completion(ctx) end
    if not record or record.status~='running' then
        local active=pages.actions[initial] or ({find=true,puzzle=true,battle=true,loading=true})[initial]
        local entry=ctx.identity_verified and ({home=true,task_list=true,ready=true})[initial]
        if not active and not entry then return stop(ctx,'shimen_task_page_not_verified','blocked') end
        record={status='running',attempts=0,find_attempts=0,find_retry_pending=initial=='retry' and 1 or 0}
        progress.write(ctx,'shimen','running','task_page_observed',record)
    end
    if step~='advance' and step~='complete' and step~='daily' then
        return stop(ctx,'shimen_step_requires_calibration')
    end
    if ctx.config.shimen_puzzle_family and pages.state()~='puzzle' then
        return stop(ctx,'shimen_puzzle_page_not_verified')
    end
    local deadline=os.time()+(ctx.config.shimen_timeout or 1800)
    local last_state,actions=nil,0
    local puzzle_attempted=record.stage=='puzzle_exit_requires_delivery_verification'
    while os.time()<deadline do
        local state=pages.state()
        if state~=last_state then log.write(ctx,'state','shimen '..state);last_state=state end
        if state=='puzzle_retry' and puzzle_attempted then
            progress.write(ctx,'shimen','running','puzzle_failed_requires_annotation',record)
            return stop(ctx,'puzzle_game_result_not_verified')
        elseif state=='puzzle' then
            puzzle_attempted=true
            local prepared,prepare_reason=materials.prepare(ctx,'shimen','puzzle')
            if not prepared then return stop(ctx,prepare_reason) end
            local solved,reason=require('tasks.shimen.puzzle').solve(ctx,ctx.config.shimen_puzzle_family or 'auto')
            if not solved then return stop(ctx,reason) end
            progress.write(ctx,'shimen','running','puzzle_exit_requires_delivery_verification',record)
            if step=='advance' then return result('paused','one_minigame_completed') end
        elseif state=='find' then
            local outcome=find(ctx,record)
            if outcome.reason=='one_minigame_completed' then
                if step=='advance' then return outcome end
            elseif step~='advance' and outcome.status~='blocked' and
                ({find_icon_not_found=true,find_target_unknown=true,find_time_expired=true})[outcome.reason] and
                device.wait(function() return pages.state()=='retry' end,120,300) then
                log.write(ctx,'find_retry_pending','task=shimen reason='..outcome.reason)
            else return outcome end
        elseif state=='story_dialogue' then
            actions=actions+1
            if actions>12 then return stop(ctx,'shimen_action_limit') end
            local fingerprint=require('common.list_navigation').fingerprint
            local view={50,1140,850,1270}
            local before=fingerprint(view)
            if not device.tap(ctx,pages.features.story_dialogue,'shimen_story_dialogue') or
                not device.wait(function()
                    return pages.state()~='story_dialogue' or fingerprint(view)~=before
                end,20) then
                return stop(ctx,'shimen_story_dialogue_not_changed')
            end
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
                materials.clear(ctx)
                progress.write(ctx,'shimen','running','delivery_verified',record)
                log.write(ctx,'shimen_delivery','idle_page=true')
                snapshot.capture(ctx,'shimen_completion_evidence','debug')
                if step=='advance' then return result('paused','one_task_completed') end
                record.attempts=(record.attempts or 0)+1
                record.find_attempts=0;record.find_retry_pending=0
                progress.write(ctx,'shimen','running','accept_reserved',record)
                if not device.tap(ctx,pages.features.accept,'shimen_accept') or
                    not device.wait(function() return pages.state()~='ready' end,20) then
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
            if not ctx.identity_verified then
                if not require('common.navigation').prepare_recorded(ctx) then
                    return stop(ctx,'role_identity_not_verified','blocked')
                end
            else
                return audit_existing_completion(ctx)
            end
        elseif state=='task_list' then
            if not ctx.identity_verified then
                if not require('common.navigation').prepare_recorded(ctx) then
                    return stop(ctx,'role_identity_not_verified','blocked')
                end
            else
                local ok,reason=open_list_card(ctx)
                if not ok then return stop(ctx,reason) end
            end
        elseif state=='idle' then
            if not ctx.identity_verified then return stop(ctx,'role_identity_not_verified','blocked') end
            materials.clear(ctx)
            progress.write(ctx,'shimen','paused','one_task_completed',record)
            snapshot.capture(ctx,'shimen_completion_evidence','debug')
            return result('paused','one_task_completed')
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
