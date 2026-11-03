local M = {}
local pages = require('tasks.zhuagui.pages')
local device = require('common.device')
local log = require('dfx.log')
local snapshot = require('dfx.snapshot')
local materials=require('dfx.materials')
local progress = require('progress')
local list=require('common.list_navigation')
local function result(status,reason,evidence)
    return {status=status,reason=reason,failure_evidence=evidence}
end
local function stop_puzzle(ctx,reason)
    -- Preserve the primary outcome even when either evidence channel fails.
    pcall(materials.keep,ctx,reason)
    local captured,evidence=pcall(snapshot.capture,ctx,reason)
    return result('paused',reason,captured and evidence or nil)
end
local function act(ctx,feature,label)
    return device.tap(ctx,feature,label)
end
local function is_active(state)
    return state=='go' or state=='depart' or state=='dialogue' or state=='find' or state=='battle' or state=='retry' or state=='puzzle' or state=='puzzle_retry'
end
local function resume_active(ctx)
    local record=progress.read(ctx,'zhuagui')
    if not record or record.status~='running' then
        progress.write(ctx,'zhuagui','running','active_page_observed',
            {attempts=0,find_retries=0,find_retry_pending=pages.state()=='retry' and 1 or 0,puzzle_retries=0})
    end
    return result('running','existing_task_resumed_no_accept')
end
local function finish_completed(ctx)
    if not ctx.identity_verified or ctx.config.business_date~=os.date('%Y%m%d') or pages.state()~='quota_completed_card' then
        snapshot.capture(ctx,'zhuagui_completion_not_verified')
        return result('blocked','completion_card_not_verified')
    end
    materials.clear(ctx)
    progress.write(ctx,'zhuagui','done','completion_card_verified',progress.read(ctx,'zhuagui'))
    snapshot.capture(ctx,'zhuagui_completion_card','debug')
    log.write(ctx,'zhuagui_completed','completion_card=true')
    return result('done','all_tasks_completed_gourds_unopened')
end
function M.observe(ctx)
    log.write(ctx,'zhuagui_observe','state=' .. pages.state() .. ' no_actions=true')
end
local function open_list_card(ctx)
    local spec={name='zhuagui_entry',page=pages.features.task_list_title,
        valid=function() local s=pages.state();return s=='task_list' or s=='quota_completed_card' end,
        inspect=function()
            if pages.state()=='quota_completed_card' then return {kind='completed'} end
            if require('common.detector').present(pages.features.task_card) then
                return {kind='entry',feature=pages.features.task_card}
            end
        end}
    local match,reason=list.find(ctx,spec)
    if not match then return false,reason=='target_not_found' and 'task_card_not_found_after_scroll' or 'task_list_changed' end
    -- A notice can cover the card after scanning. Failed guarded taps send no
    -- input, so wait for an actionable card without repeating a sent tap.
    if not device.wait(function() return list.activate(ctx,spec,match,'zhuagui_open_detail') end,20) then
        return false,'task_list_changed'
    end
    return true
end
local function enter(ctx)
    local state=pages.state()
    if is_active(state) then return resume_active(ctx) end
    if state=='rules' then
        if not act(ctx,pages.features.rules,'zhuagui_close_rules') then return result('blocked','rules_changed') end
        if not device.wait(function() return pages.state()=='ready_cost_three' end,10) then
            return result('paused','rules_return_not_verified')
        end
        state=pages.state()
    end
    if state=='ready_cost_three' then
        -- Identity remains valid within this role's task loop. start() still
        -- verifies the current ready page before each accept.
        if ctx.identity_verified then
            return result('running','entered_ready_cost_three_no_task_accepted')
        end
        if not act(ctx,pages.features.cancel,'zhuagui_close_ready_for_identity') then
            return result('blocked','cancel_not_verified')
        end
        state=pages.state()
    end
    if state=='task_list' then
        if not act(ctx,require('common.assets.home_tab'),'zhuagui_preflight_return_home') then
            return result('blocked','home_tab_not_verified')
        end
    end
    if not ctx.identity_verified and not require('common.navigation').prepare_recorded(ctx) then
        return result('blocked','saved_role_not_ready')
    end
    if not act(ctx,pages.features.home_tasks,'zhuagui_open_task_list') then
        return result('blocked','home_task_entry_not_verified')
    end
    if not device.wait(function() local s=pages.state(); return s=='task_list' or s=='quota_completed_card' or is_active(s) end,20) then
        snapshot.capture(ctx,'zhuagui_task_list_not_verified')
        return result('paused','task_list_requires_calibration')
    end
    -- With an unfinished job, the home entry opens its NPC directly.
    if is_active(pages.state()) then return resume_active(ctx) end
    if pages.state()=='quota_completed_card' then return result('running','entered_completion_list_no_accept') end
    local opened,reason=open_list_card(ctx)
    if not opened then
        snapshot.capture(ctx,reason)
        return result('blocked',reason)
    end
    if pages.state()=='quota_completed_card' then return result('running','entered_completion_list_no_accept') end
    if not device.wait(function() local s=pages.state();return s=='ready_cost_three' or s=='rules' end,20) then
        snapshot.capture(ctx,'zhuagui_entry_result')
        return result('paused','entry_postcondition_not_verified')
    end
    if pages.state()=='rules' then
        if not act(ctx,pages.features.rules,'zhuagui_close_rules') or
            not device.wait(function() return pages.state()=='ready_cost_three' end,20) then
            return result('paused','rules_return_not_verified')
        end
    end
    return result('running','entered_ready_cost_three_no_task_accepted')
end
local function start(ctx)
    if not ctx.identity_verified then return result('blocked','role_identity_not_verified') end
    if pages.state()~='ready_cost_three' then return result('blocked','ready_and_cost_not_verified') end
    local existing=progress.read(ctx,'zhuagui')
    if existing and existing.status=='running' then return result('blocked','active_attempt_already_reserved') end
    local counters={attempts=(existing and existing.attempts or 0)+1,
        find_retries=0,find_retry_pending=0,puzzle_retries=0}
    progress.write(ctx,'zhuagui','running','start_requested',counters)
    if not act(ctx,pages.features.accept,'zhuagui_accept') then
        return result('blocked','accept_disappeared_reservation_retained')
    end
    return result('running','one_task_reserved_start_requested')
end
local function drive(ctx,stop_after_one)
    local record=progress.read(ctx,'zhuagui')
    if not record then
        if not is_active(pages.state()) and pages.state()~='quota_dialogue' then
            return result('blocked','active_task_page_not_verified')
        end
        resume_active(ctx)
        record=progress.read(ctx,'zhuagui')
    end
    local deadline=os.time()+(ctx.config.zhuagui_timeout or 1800)
    local unknown_since,last_state,heartbeat=nil,nil,os.time()
    local actions=0
    while os.time()<deadline do
        local state=pages.state()
        if state~=last_state then
            -- Bound repeated actions on one page, not the whole automatic job.
            -- Battles and recognition pages prove that the dialogue advanced.
            actions=0
            log.write(ctx,'state','zhuagui ' .. state)
            last_state=state
        end
        if state=='quota_dialogue' then
            if not act(ctx,pages.features.quota_dialogue,'close_completed_ghost_dialogue') or
                not device.wait(function() return pages.state()=='task_list' or pages.state()=='quota_completed_card' or
                    require('common.detector').present(require('common.assets.home_dungeon')) end,20) then
                snapshot.capture(ctx,'quota_dialogue_not_closed');return result('paused','quota_dialogue_not_closed')
            end
            if require('common.detector').present(require('common.assets.home_dungeon')) then
                if not require('common.navigation').prepare_recorded(ctx) then return result('blocked','saved_role_not_ready') end
                if not act(ctx,pages.features.home_tasks,'reopen_ghost_completion_list') or
                    not device.wait(function() return pages.state()=='task_list' or pages.state()=='quota_completed_card' end,20) then
                    return result('paused','completion_list_changed')
                end
            end
            state=pages.state()
        end
        if (state=='ready_cost_three' or state=='quota_idle' or state=='quota_completed_card') and
            ctx.config.verify_role and not ctx.identity_verified then
            if not require('common.navigation').prepare_recorded(ctx) then return result('blocked','saved_role_not_ready') end
            local entered=enter(ctx)
            if entered.status~='running' then return entered end
            state=pages.state()
        end
        if state=='ready_cost_three' or state=='quota_idle' or state=='quota_completed_card' then
            if state=='quota_completed_card' then
                return finish_completed(ctx)
            end
            if state=='quota_idle' then
                materials.clear(ctx)
                if not act(ctx,pages.features.cancel,'zhuagui_close_final_detail') then
                    return result('paused','completion_list_entry_not_verified')
                end
            else
                if record.status=='running' then
                    materials.clear(ctx)
                    progress.write(ctx,'zhuagui','paused','one_task_completed',record)
                    record.status='paused'
                    log.write(ctx,'zhuagui_delivery','idle_page=true')
                    snapshot.capture(ctx,'zhuagui_completion_evidence','debug')
                elseif record.stage~='one_task_completed' then
                    return result('blocked','unverified_progress_stage')
                end
                if stop_after_one then return result('paused','one_task_completed') end
                local entered=enter(ctx)
                if entered.status~='running' then return entered end
                if pages.state()=='ready_cost_three' then
                    local started=start(ctx)
                    if started.status~='running' then return started end
                elseif not is_active(pages.state()) then
                    return result('paused','next_task_page_not_verified')
                end
                record=progress.read(ctx,'zhuagui')
                actions=0
            end
        elseif record.status~='running' then
            return result('blocked','completed_record_does_not_match_page')
        elseif state=='task_list' then
            if not device.wait(function() return pages.state()~='task_list' end,6,200) then
                local spec={name='zhuagui_completed',page=pages.features.task_list_title,
                    valid=function() local s=pages.state();return s=='task_list' or s=='quota_completed_card' end,
                    inspect=function() if pages.state()=='quota_completed_card' then return {kind='completed'} end end}
                local match,reason=list.find(ctx,spec)
                if not match then
                    local current=pages.state()
                    if reason=='list_changed' and (is_active(current) or current=='ready_cost_three' or
                        current=='quota_idle' or current=='quota_dialogue' or current=='quota_completed_card') then
                        -- Delivery can settle on the NPC while the list scanner
                        -- is stabilizing. Re-enter the guarded task loop there.
                        log.write(ctx,'screen_resume','zhuagui completion_scan state='..current)
                    else
                        reason=reason=='target_not_found' and 'completed_card_not_found' or 'completion_list_changed'
                        snapshot.capture(ctx,reason)
                        return result('paused',reason)
                    end
                end
            end
        elseif state=='battle' then
            mSleep(1000)
        elseif state=='puzzle_retry' then
            if (record.puzzle_retries or 0)>=1 then
                return stop_puzzle(ctx,'puzzle_retry_not_authorized')
            end
            materials.keep(ctx,'puzzle_game_result_not_verified')
            record.puzzle_retries=(record.puzzle_retries or 0)+1
            progress.write(ctx,'zhuagui','running','authorized_puzzle_resume',record)
            log.write(ctx,'puzzle_retry','attempt='..record.attempts..' retry=1 no_new_accept=true')
            if not act(ctx,pages.features.puzzle.retry_button,'resume_visible_puzzle') then return result('paused','puzzle_retry_target_changed') end
        elseif state=='puzzle' then
            local prepared,prepare_reason=materials.prepare(ctx,'zhuagui','puzzle')
            if not prepared then return result('paused',prepare_reason) end
            local solved,reason=require('tasks.zhuagui.puzzle').solve(ctx)
            if not solved then return stop_puzzle(ctx,reason) end
            log.write(ctx,'puzzle_solved','attempt='..record.attempts)
        elseif state=='find' then
            local prepared,prepare_reason=materials.prepare(ctx,'zhuagui','find')
            if not prepared then return result('paused',prepare_reason) end
            local solved,reason,category=require('tasks.zhuagui.find').solve(ctx)
            if not solved then
                materials.keep(ctx,reason)
                log.write(ctx,'error','task=zhuagui attempt='..record.attempts..' reason='..reason..' category='..tostring(category))
                local evidence=snapshot.capture(ctx,reason)
                local retryable=({find_icon_not_found=true,find_time_expired=true,find_target_unknown=true,
                    find_click_not_confirmed=true,wine_requires_specific_calibration=true,
                    find_target_requires_calibration=true,catalog_page_changed=true})[reason]
                if not retryable then return result('paused',reason,evidence) end
                record.find_retry_pending=1
                progress.write(ctx,'zhuagui','running','find_recognition_failed',record)
                if not device.wait(function()
                    local next_state=pages.state()
                    return next_state=='retry' or next_state=='dialogue'
                end,120,300) then
                    return result('paused',reason)
                end
                log.write(ctx,'find_retry_pending','reason=' .. reason)
            end
        elseif state=='dialogue' or state=='go' or state=='depart' or state=='retry' then
            local function free_action_verified()
                return pages.state()==state and not require('common.detector').present(pages.features.accept) and
                    record.status=='running'
            end
            if not free_action_verified() then
                if not device.wait(function() return pages.state()~=state end,10,200) then
                    snapshot.capture(ctx,'free_action_precondition_not_verified')
                    return result('paused','free_action_precondition_not_verified')
                end
                log.write(ctx,'action_transition','zhuagui '..state..' changed_before_free_action no_click=true')
            else
                actions=actions+1
                if actions>12 then snapshot.capture(ctx,'action_limit'); return result('paused','action_limit') end
                if state=='retry' or (state=='dialogue' and record.find_retry_pending==1) then
                    if record.find_retry_pending~=1 then
                        snapshot.capture(ctx,'unexpected_retry_page')
                        return result('paused','retry_without_recognition_failure')
                    end
                    if (record.find_retries or 0)>=3 then
                        snapshot.capture(ctx,'find_retry_limit'); return result('paused','find_retry_limit')
                    end
                    record.find_retries=(record.find_retries or 0)+1
                    record.find_retry_pending=0
                    progress.write(ctx,'zhuagui','running','free_find_retry_reserved',record)
                    log.write(ctx,'find_retry','attempt=' .. record.attempts .. ' retries=' .. record.find_retries ..
                        '/3 no_new_accept=true')
                    actions=0
                end
                local feature=state=='dialogue' and pages.features.dialogue_next or pages.features[state]
                if not device.tap(ctx,feature,'zhuagui_' .. state,free_action_verified) then
                    if not device.wait(function() return pages.state()~=state end,10,200) then
                        snapshot.capture(ctx,'free_action_target_changed')
                        return result('paused','free_action_target_changed')
                    end
                    log.write(ctx,'action_transition','zhuagui '..state..' changed_during_free_action no_click=true')
                end
                device.wait(function() return pages.state()~=state end,6)
            end
        else
            unknown_since=unknown_since or os.time()
            if os.time()-unknown_since>=12 then
                snapshot.capture(ctx,'zhuagui_unknown_state')
                return result('paused','new_task_requires_calibration')
            end
        end
        if state~='active_uncalibrated' and state~='unknown' then unknown_since=nil end
        if os.time()-heartbeat>=30 then
            log.write(ctx,'waiting','zhuagui ' .. state)
            snapshot.capture(ctx,'zhuagui_waiting','debug')
            heartbeat=os.time()
        end
        mSleep(500)
    end
    snapshot.capture(ctx,'zhuagui_timeout')
    return result('failed','zhuagui_timeout')
end
function M.run(ctx)
    assert(ctx.config.allow_reward_claim==false,'reward claims forbidden')
    local dismiss=require('common.navigation').dismiss_overlays
    if dismiss and not dismiss(ctx) then return result('paused','overlay_not_closed') end
    M.observe(ctx)
    local step=ctx.config.step
    if step=='observe' then return result('paused','observation_only') end
    if step=='browse' then
        if not is_active(pages.state()) then return result('blocked','active_task_page_not_verified') end
        resume_active(ctx)
        return require('tasks.zhuagui.catalog').collect(ctx)
    end
    if step=='advance' then return drive(ctx,true) end
    if step=='complete' or step=='daily' then
        if pages.state()=='quota_completed_card' and ctx.identity_verified then return finish_completed(ctx) end
        local current=progress.read(ctx,'zhuagui')
        if current and current.status=='running' and pages.state()~='unknown' then return drive(ctx,false) end
        if is_active(pages.state()) or pages.state()=='quota_dialogue' then return drive(ctx,false) end
        local entered=enter(ctx)
        if entered.status~='running' then return entered end
        if pages.state()=='quota_completed_card' then return finish_completed(ctx) end
        if is_active(pages.state()) then return drive(ctx,false) end
        local started=start(ctx)
        if started.status~='running' then return started end
        return drive(ctx,false)
    end
    if step=='enter' or step=='start' then
        local entered=enter(ctx)
        if entered.status~='running' or step=='enter' then return entered end
        return start(ctx)
    end
    snapshot.capture(ctx,'zhuagui_unverified_state')
    return result('blocked','zhuagui_page_requires_calibration')
end
return M
