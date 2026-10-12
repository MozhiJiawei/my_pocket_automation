local M = {}
local pages = require('tasks.zhuagui.pages')
local device = require('common.device')
local log = require('dfx.log')
local snapshot = require('dfx.snapshot')
local progress = require('progress')
local counter=require('tasks.zhuagui.counter')
local function result(status,reason) return {status=status,reason=reason} end
local function act(ctx,feature,label)
    return device.tap(ctx,feature,label)
end
local function is_active(state)
    return state=='go' or state=='depart' or state=='dialogue' or state=='find' or state=='battle' or state=='retry' or state=='puzzle' or state=='puzzle_retry'
end
local function resume_active(ctx)
    local record=progress.read(ctx,'zhuagui')
    if not record or record.status~='running' then return result('blocked','active_task_ownership_missing') end
    return result('running','existing_task_resumed_no_accept')
end
function M.observe(ctx)
    log.write(ctx,'zhuagui_observe','state=' .. pages.state() .. ' no_actions=true')
end
local function open_list_card(ctx)
    -- Card order and the list's retained scroll position are not fixed.
    for page=1,13 do
        local state=pages.state()
        if state~='task_list' and state~='quota_completed_card' then return false,'task_list_changed' end
        if act(ctx,pages.features.task_card,'zhuagui_open_detail') then return true end
        if page==13 then break end
        local from,to={780,1250},{780,570}
        if page>4 then from,to=to,from end
        if not device.swipe(ctx,pages.features.task_list_title,'zhuagui_find_task_card',from,to) then
            return false,'task_list_changed'
        end
    end
    return false,'task_card_not_found_after_scroll'
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
        -- verifies the visible count and persists the fee before each accept.
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
    local owned=progress.read(ctx,'zhuagui')
    if owned and owned.attempts==25 then return result('running','entered_completion_list_no_accept') end
    local opened,reason=open_list_card(ctx)
    if not opened then
        snapshot.capture(ctx,reason)
        return result('blocked',reason)
    end
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
    log.write(ctx,'energy_policy','zhuagui per_task=3 cap=' .. tostring(ctx.config.zhuagui_budget or 0))
    return result('running','entered_ready_cost_three_no_task_accepted')
end
local function start(ctx)
    if not ctx.identity_verified then return result('blocked','role_identity_not_verified') end
    if pages.state()~='ready_cost_three' then return result('blocked','ready_and_cost_not_verified') end
    local cap=ctx.config.zhuagui_budget or 0
    if type(cap)~='number' or cap<0 or cap>75 or cap%3~=0 then return result('blocked','invalid_energy_cap') end
    local existing=progress.read(ctx,'zhuagui')
    if existing and existing.status=='running' then return result('blocked','active_attempt_already_reserved') end
    if existing and existing.status=='done' then return result('done','daily_done_skip') end
    local reserved=existing and existing.reserved_energy or 0
    if reserved+3>cap then return result('blocked','energy_budget_exhausted') end
    local count=counter.read()
    if count==nil or count~=(existing and existing.attempts or 0) then return result('paused','count_requires_calibration') end
    local counters={reserved_energy=reserved+3,attempts=(existing and existing.attempts or 0)+1,
        completed_count=existing and existing.completed_count or 0,find_retries=0,find_retry_pending=0,puzzle_retries=0}
    progress.write(ctx,'zhuagui','running','start_requested',counters)
    log.write(ctx,'energy_reservation','zhuagui reserved=' .. counters.reserved_energy .. ' cap=' .. cap)
    if not act(ctx,pages.features.accept,'zhuagui_accept') then
        return result('blocked','accept_disappeared_reservation_retained')
    end
    return result('running','one_task_reserved_start_requested')
end
local function drive(ctx,stop_after_one)
    local record=progress.read(ctx,'zhuagui')
    if not record then return result('blocked','active_task_ownership_missing') end
    local deadline=os.time()+(ctx.config.zhuagui_timeout or 1800)
    local unknown_since,last_state,heartbeat=nil,nil,os.time()
    local actions,completion_scrolls=0,0
    while os.time()<deadline do
        local state=pages.state()
        if state~=last_state then log.write(ctx,'state','zhuagui ' .. state); last_state=state end
        if state=='quota_dialogue' then
            if record.attempts~=25 then return result('blocked','quota_dialogue_ledger_mismatch') end
            if not act(ctx,pages.features.quota_dialogue,'close_completed_ghost_dialogue') or
                not device.wait(function() return pages.state()=='task_list' or pages.state()=='quota_completed_card' end,20) then
                snapshot.capture(ctx,'quota_dialogue_not_closed');return result('paused','quota_dialogue_not_closed')
            end
            state=pages.state()
        end
        if (state=='ready_cost_three' or state=='quota_idle' or state=='quota_completed_card') and
            ctx.config.verify_role and not ctx.identity_verified then
            if not require('common.navigation').prepare_recorded(ctx) then return result('blocked','saved_role_not_ready') end
            local entered=enter(ctx)
            if entered.status~='running' then return entered end
            state=pages.state()
            completion_scrolls=0
            if record.attempts~=25 and state~='ready_cost_three' then
                return result('blocked','completion_page_after_identity_not_verified')
            end
        end
        if state=='ready_cost_three' or state=='quota_idle' or state=='quota_completed_card' then
            -- At the daily cap the game closes the detail and moves this card
            -- to the list bottom. Its explicit completed stamp replaces N/25.
            if state=='quota_completed_card' and record.attempts~=25 then
                return result('blocked','completed_card_ledger_mismatch')
            end
            local count=state=='quota_completed_card' and 25 or counter.read()
            if count==nil then snapshot.capture(ctx,'count_requires_calibration'); return result('paused','count_requires_calibration') end
            if count~=record.attempts then return result('blocked','completion_count_mismatch') end
            if record.status=='running' then
                if (record.completed_count or 0)~=record.attempts-1 then return result('blocked','completion_ledger_mismatch') end
                record.completed_count=record.attempts
                progress.write(ctx,'zhuagui','paused','one_task_completed',record)
                record.status='paused'
                log.write(ctx,'zhuagui_completed','count=' .. count .. ' reserved_energy=' .. record.reserved_energy)
                snapshot.capture(ctx,'zhuagui_completion_evidence','debug')
            elseif record.stage~='one_task_completed' then
                return result('blocked','unverified_progress_stage')
            end
            if count==25 then
                progress.write(ctx,'zhuagui','done','all_25_completed_gourds_unopened',record)
                log.write(ctx,'reward_policy','zhuagui gourds_opened=false')
                return result('done','all_25_completed_gourds_unopened')
            end
            if count>=(ctx.config.zhuagui_target or 25) then
                return result('done','target_'..count..'_completed_gourds_unopened')
            end
            if stop_after_one then return result('paused','one_task_completed') end
            local entered=enter(ctx)
            if entered.status~='running' then return entered end
            local started=start(ctx)
            if started.status~='running' then return started end
            record=progress.read(ctx,'zhuagui')
            actions=0
        elseif record.status~='running' then
            return result('blocked','completed_record_does_not_match_page')
        elseif state=='task_list' and record.attempts==25 then
            if completion_scrolls>=4 then
                snapshot.capture(ctx,'completed_card_not_found')
                return result('paused','completed_card_not_found')
            end
            if not device.swipe(ctx,pages.features.task_list_title,'zhuagui_find_completed_card',{800,1260},{800,600}) then
                snapshot.capture(ctx,'completion_list_changed')
                return result('paused','completion_list_changed')
            end
            completion_scrolls=completion_scrolls+1
        elseif state=='battle' then
            mSleep(1000)
        elseif state=='puzzle_retry' then
            if ctx.config.puzzle_retry_attempt~=record.attempts or (record.puzzle_retries or 0)>=1 then
                snapshot.capture(ctx,'puzzle_retry_not_authorized')
                return result('paused','puzzle_retry_not_authorized')
            end
            record.puzzle_retries=(record.puzzle_retries or 0)+1
            progress.write(ctx,'zhuagui','running','authorized_puzzle_resume',record)
            log.write(ctx,'puzzle_retry','owned_attempt='..record.attempts..' retry=1 no_new_accept=true')
            if not act(ctx,pages.features.puzzle.retry_button,'resume_owned_puzzle') then return result('paused','puzzle_retry_target_changed') end
        elseif state=='puzzle' then
            local solved,reason=require('tasks.zhuagui.puzzle').solve(ctx)
            if not solved then snapshot.capture(ctx,reason);return result('paused',reason) end
            log.write(ctx,'puzzle_solved','attempt='..record.attempts)
        elseif state=='find' then
            local solved,reason,category=require('tasks.zhuagui.find').solve(ctx)
            if not solved then
                log.write(ctx,'error','task=zhuagui attempt='..record.attempts..' reason='..reason..' category='..tostring(category))
                snapshot.capture(ctx,reason)
                local retryable=({find_icon_not_found=true,find_time_expired=true,find_target_unknown=true,
                    find_click_not_confirmed=true,wine_requires_specific_calibration=true,
                    find_target_requires_calibration=true})[reason]
                if not retryable then return result('paused',reason) end
                record.find_retry_pending=1
                progress.write(ctx,'zhuagui','running','find_recognition_failed',record)
                if not device.wait(function() return pages.state()=='retry' end,120,300) then
                    return result('paused',reason)
                end
                log.write(ctx,'find_retry_pending','reason=' .. reason)
            end
        elseif state=='dialogue' or state=='go' or state=='depart' or state=='retry' then
            actions=actions+1
            if actions>12 then snapshot.capture(ctx,'action_limit'); return result('paused','action_limit') end
            if state=='retry' then
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
                log.write(ctx,'find_retry','attempt=' .. record.attempts .. ' retries=' .. record.find_retries .. '/3 no_new_accept=true')
                actions=0
            end
            local feature=state=='dialogue' and pages.features.dialogue_next or pages.features[state]
            if act(ctx,feature,'zhuagui_' .. state) then
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
    local target=ctx.config.zhuagui_target or 25
    assert(type(target)=='number' and target>=1 and target<=25 and target%1==0,'invalid ghost target')
    M.observe(ctx)
    local step=ctx.config.step
    if step=='observe' then return result('paused','observation_only') end
    if step=='browse' then
        if not progress.read(ctx,'zhuagui') then return result('blocked','active_task_ownership_missing') end
        return require('tasks.zhuagui.catalog').collect(ctx)
    end
    local record=progress.read(ctx,'zhuagui')
    if record and record.status=='done' then return result('done','daily_done_skip') end
    if step=='advance' then return drive(ctx,true) end
    if step=='complete' or step=='daily' then
        if record then
            if pages.state()=='unknown' or (record.attempts~=25 and pages.state()=='task_list') then
                local entered=enter(ctx)
                if entered.status~='running' then return entered end
            end
            return drive(ctx,false)
        end
        local entered=enter(ctx)
        if entered.status~='running' then return entered end
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
