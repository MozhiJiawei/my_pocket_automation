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
    return state=='go' or state=='depart' or state=='dialogue' or state=='find' or state=='battle' or state=='retry'
end
local function resume_active(ctx)
    local record=progress.read(ctx,'zhuagui')
    if not record or record.status~='running' then return result('blocked','active_task_ownership_missing') end
    return result('running','existing_task_resumed_no_accept')
end
function M.observe(ctx)
    log.write(ctx,'zhuagui_observe','state=' .. pages.state() .. ' no_actions=true')
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
    if not device.wait(function() local s=pages.state(); return s=='task_list' or is_active(s) end,20) then
        snapshot.capture(ctx,'zhuagui_task_list_not_verified')
        return result('paused','task_list_requires_calibration')
    end
    -- With an unfinished job, the home entry opens its NPC directly.
    if is_active(pages.state()) then return resume_active(ctx) end
    if not act(ctx,pages.features.task_card,'zhuagui_open_detail') then
        return result('blocked','task_card_disappeared')
    end
    if not device.wait(function() return pages.state()=='ready_cost_three' end,20) then
        snapshot.capture(ctx,'zhuagui_entry_result')
        return result('paused','entry_postcondition_not_verified')
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
        completed_count=existing and existing.completed_count or 0}
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
    local actions=0
    while os.time()<deadline do
        local state=pages.state()
        if state~=last_state then log.write(ctx,'state','zhuagui ' .. state); last_state=state end
        if state=='ready_cost_three' or state=='quota_idle' then
            local count=counter.read()
            if count==nil then snapshot.capture(ctx,'count_requires_calibration'); return result('paused','count_requires_calibration') end
            if count~=record.attempts then return result('blocked','completion_count_mismatch') end
            if record.status=='running' then
                if (record.completed_count or 0)~=record.attempts-1 then return result('blocked','completion_ledger_mismatch') end
                record.completed_count=record.attempts
                progress.write(ctx,'zhuagui','paused','one_task_completed',record)
                record.status='paused'
                log.write(ctx,'zhuagui_completed','count=' .. count .. ' reserved_energy=' .. record.reserved_energy)
                snapshot.capture(ctx,'zhuagui_completion_evidence')
            elseif record.stage~='one_task_completed' then
                return result('blocked','unverified_progress_stage')
            end
            if count==25 then
                progress.write(ctx,'zhuagui','done','all_25_completed_gourds_unopened',record)
                log.write(ctx,'reward_policy','zhuagui gourds_opened=false')
                return result('done','all_25_completed_gourds_unopened')
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
        elseif state=='battle' then
            mSleep(1000)
        elseif state=='find' then
            local solved,reason=require('tasks.zhuagui.find').solve(ctx)
            if not solved then snapshot.capture(ctx,reason); return result('paused',reason) end
        elseif state=='dialogue' or state=='go' or state=='depart' or state=='retry' then
            actions=actions+1
            if actions>12 then snapshot.capture(ctx,'action_limit'); return result('paused','action_limit') end
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
            snapshot.capture(ctx,'zhuagui_waiting')
            heartbeat=os.time()
        end
        mSleep(500)
    end
    snapshot.capture(ctx,'zhuagui_timeout')
    return result('failed','zhuagui_timeout')
end
function M.run(ctx)
    assert(ctx.config.allow_reward_claim==false,'reward claims forbidden')
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
            if pages.state()=='unknown' or pages.state()=='task_list' then
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
