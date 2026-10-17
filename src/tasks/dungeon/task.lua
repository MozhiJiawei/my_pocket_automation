local log = require('dfx.log')
local pages = require('tasks.dungeon.pages')
local device = require('common.device')
local progress = require('progress')
local detector = require('common.detector')
local snapshot = require('dfx.snapshot')
local navigation = require('common.navigation')
local list=require('common.list_navigation')
local M = {}
local enter,select_card
local function result(status, reason) return {status=status, reason=reason} end
local function act(ctx, feature, label)
    assert(device.tap(ctx, feature, label), 'action_target_disappeared:' .. label)
end
function M.observe(ctx)
    log.write(ctx, 'dungeon_observe', 'state=' .. pages.state() .. ' no_actions=true')
end
local function start(ctx, id)
    if not ctx.identity_verified then return result('blocked','role_identity_not_verified') end
    if pages.state() ~= id .. '_ready' then return result('blocked', 'ready_page_not_verified') end
    local record=progress.read(ctx,id)
    if record and record.stage=='start_requested' then return result('blocked', 'start_postcondition_not_verified') end
    progress.write(ctx, id, 'running', 'start_requested')
    act(ctx, pages.features.start, id .. '_start')
    return result('running', 'start_requested')
end
local function switch_completed(ctx, target)
    local state=pages.state()
    local prior,next_id=state:match('^switch_(%w+)_(%w+)$')
    if not prior or next_id~=target then return false end
    local previous = progress.read(ctx, prior)
    if not previous or previous.status~='done' then return false end
    if not ctx.identity_verified then return false end
    act(ctx, pages.features[state], 'switch_after_verified_completion')
    return true
end
local function cached_complete(ctx,id)
    local record=progress.read(ctx,id)
    return ctx.identity_verified and ctx.config.business_date==os.date('%Y%m%d') and
        record and record.status=='done' and (record.stage=='reward_claimed' or
        (ctx.account.claim_dungeon_rewards~=true and record.stage=='reward_intentionally_unclaimed'))
end
local function audit_claimed(ctx,id)
    if not ctx.identity_verified or ctx.config.business_date~=os.date('%Y%m%d') or not pages.reward_claimed(id) then
        return result('blocked','claimed_card_not_verified')
    end
    snapshot.capture(ctx,id..'_claimed_card','debug')
    progress.write(ctx,id,'done','reward_claimed')
    log.write(ctx,'dungeon_reward_claimed',id..' list_marker=true')
    return result('done','reward_claimed')
end
local function finish_claim(ctx,id)
    -- Success dialogs may close automatically; the durable game list mark is the postcondition.
    if not device.wait(function()
        return detector.present(pages.features.claim_receipt_close) or pages.state():match('^list_')
    end,20) then return result('paused','reward_claim_not_verified_no_repeat') end
    if detector.present(pages.features.claim_receipt_close) then
        if not device.tap(ctx,pages.features.claim_receipt_close,id..'_close_claim_receipt') and
            not pages.state():match('^list_') then return result('paused','reward_receipt_close_not_verified') end
    end
    if not device.wait(function() return pages.state():match('^list_') end,20) then
        return result('paused','reward_claim_not_verified_no_repeat')
    end
    local match=select_card(ctx,id,true)
    if not match or match.kind~='claimed' then return result('paused','reward_claim_not_verified_no_repeat') end
    return audit_claimed(ctx,id)
end
local function finish(ctx, id)
    local state
    if not device.wait(function()
        state=pages.state()
        return state==id..'_done' or state==id..'_reward_sealed'
    end,20) then
        snapshot.capture(ctx,id..'_completion_not_verified')
        return result('blocked', 'completion_not_verified')
    end
    snapshot.capture(ctx, id .. '_completion_evidence', 'debug')
    if not ctx.identity_verified then
        if not navigation.prepare_recorded or not navigation.prepare_recorded(ctx) then
            return result('blocked','completion_role_identity_not_verified')
        end
        if not navigation.open_dungeon(ctx) or
            not device.wait(function()
                local landed=pages.state()
                return landed:match('^list_') or landed==id..'_done' or landed==id..'_reward_sealed'
            end,20) then
            return result('paused','completion_return_list_not_verified')
        end
        if pages.state():match('^list_') then
            local entered=enter(ctx,id)
            if entered.status=='done' then return entered end
            if entered.status~='running' then return entered end
        end
        state=pages.state()
    end
    if ctx.config.business_date~=os.date('%Y%m%d') or
        (state~=id..'_done' and state~=id..'_reward_sealed') then return result('blocked','completion_not_verified') end
    log.write(ctx,'dungeon_completion_audit',id..' terminal_state=true business_date='..ctx.config.business_date)
    if ctx.account.claim_dungeon_rewards==true then
        local previous=progress.read(ctx,id)
        if previous and ({reward_claim_requested=true,reward_confirmation_requested=true})[previous.stage] then
            return result('paused','reward_claim_not_verified_no_repeat')
        end
        if previous and previous.stage=='reward_claimed' then return result('done','reward_already_claimed') end
        if state==id..'_done' then
            local button=require('tasks.dungeon.assets.overview_claim')
            local opened=device.tap(ctx,button,id..'_open_sealed_gourd')
            if opened then device.wait(function() return pages.state()==id..'_reward_sealed' end,20) end
            state=pages.state()
            if state~=id..'_reward_sealed' then
                -- A completed overview can ignore its first free opening tap.
                -- Re-enter once through home; never repeat a claim request.
                if state~=id..'_done' or not navigation.return_home(ctx) then
                    return result('paused','sealed_reward_entry_requires_calibration')
                end
                log.write(ctx,'dungeon_recovery',id..' reenter_sealed_reward_once')
                if not navigation.open_dungeon(ctx) or not device.wait(function()
                    local landed=pages.state()
                    return landed:match('^list_') or landed==id..'_reward_sealed' or landed==id..'_done'
                end,20) then return result('paused','sealed_reward_entry_requires_calibration') end
                if pages.state():match('^list_') then
                    local entered=enter(ctx,id)
                    if entered.status=='done' then return entered end
                    if entered.status~='running' then return entered end
                end
            end
            state=pages.state()
        end
        if state~=id..'_reward_sealed' then return result('paused','sealed_reward_entry_requires_calibration') end
        local feature=require('tasks.dungeon.assets.claim_cost_100')
        if not detector.present(feature) then return result('paused','reward_cost_requires_calibration') end
        progress.write(ctx,id,'done','reward_claim_requested')
        if not device.tap(ctx,feature,id..'_claim_gourd_100') then
            return result('paused','reward_target_changed_reservation_retained')
        end
        if not device.wait(function() return pages.state()==id..'_claim_confirm' end,20) then
            snapshot.capture(ctx,id..'_claim_confirmation_not_verified')
            return result('paused','claim_confirmation_not_verified')
        end
        progress.write(ctx,id,'done','reward_confirmation_requested')
        if not device.tap(ctx,pages.features.claim_confirm_button,id..'_confirm_claim_100',function()
            return ctx.identity_verified and pages.state()==id..'_claim_confirm'
        end) then return result('paused','claim_confirmation_target_changed') end
        snapshot.capture(ctx,id..'_reward_claim_result','evidence')
        return finish_claim(ctx,id)
    end
    progress.write(ctx, id, 'done', 'reward_intentionally_unclaimed')
    log.write(ctx, 'reward_policy', id .. ' claim=false cost_button_forbidden')
    if state == id .. '_reward_sealed' then
        act(ctx, pages.features.overview_back, id .. '_leave_sealed_reward')
        if not device.wait(function() return pages.state()==id .. '_done' end, 10) then
            return result('paused', 'combat_done_return_page_not_verified')
        end
    end
    return result('done', id .. '_completed_reward_not_claimed')
end
local function resume_battle(ctx,id)
    -- TouchSprite's launch notice can briefly cover the bottom control.
    if not device.wait(function()
        return detector.present(pages.features.continue_battle) or pages.state()~=id..'_active'
    end,20,300) then
        snapshot.capture(ctx,'continue_battle_button_not_visible')
        return result('paused','continue_battle_button_not_visible')
    end
    local state=pages.state()
    if state=='battle' or state=='loading' or state==id..'_done' or state==id..'_reward_sealed' then
        return result('running','battle_transition_observed')
    end
    if not device.tap(ctx,pages.features.continue_battle,id..'_continue_battle',function()
        return pages.state()==id..'_active'
    end) then
        local landed=pages.state()
        if landed=='battle' or landed=='loading' or landed==id..'_done' or landed==id..'_reward_sealed' then
            return result('running','battle_transition_observed')
        end
        snapshot.capture(ctx,'continue_battle_target_changed')
        log.write(ctx,'resume_not_verified',id..' state='..pages.state()..' button='..tostring(detector.present(pages.features.continue_battle)))
        return result('paused','continue_battle_target_changed')
    end
    if not device.wait(function()
        local state=pages.state()
        return state=='battle' or state=='loading' or state==id..'_done' or state==id..'_reward_sealed'
    end,20) then return result('paused','continue_battle_postcondition_not_verified') end
    return result('running','existing_battle_resumed')
end
local function wait_battles(ctx, id, stop_after_battle)
    local deadline, unknown_since, last_state = os.time()+(ctx.config.dungeon_timeout or 3600), nil, nil
    local heartbeat = os.time()
    while os.time() < deadline do
        local state = pages.state()
        if state ~= last_state then log.write(ctx, 'state', id .. ' ' .. state); last_state=state end
        if state == id .. '_reward_sealed' or state == id .. '_done' then
            if stop_after_battle then snapshot.capture(ctx, 'next_state', 'debug'); return result('paused', 'battle_completed') end
            return finish(ctx, id)
        elseif state == 'battle' then
            unknown_since = nil
        elseif state == 'loading' then
            unknown_since = nil
        elseif state==id..'_active' then
            unknown_since=unknown_since or os.time()
            if os.time()-unknown_since>=30 then
                snapshot.capture(ctx,'dungeon_interrupted')
                return result('paused','dungeon_interrupted')
            end
        elseif state == 'reward_unknown' then
            snapshot.capture(ctx, 'unknown_reward'); return result('paused', 'reward_requires_calibration_no_claim')
        else
            unknown_since = unknown_since or os.time()
            if os.time()-unknown_since >= 30 then
                snapshot.capture(ctx, 'unknown_state'); return result('paused', 'stable_unknown_state_no_actions')
            end
        end
        if os.time()-heartbeat >= 30 then
            log.write(ctx, 'waiting', id .. ' ' .. state)
            snapshot.capture(ctx, 'waiting', 'debug')
            heartbeat=os.time()
        end
        mSleep(1000)
    end
    snapshot.capture(ctx, 'timeout')
    return result('failed', 'dungeon_timeout')
end
select_card=function(ctx, id, claimed_only)
    local def = assert(pages.definitions[id])
    local card = {}
    for k,v in pairs(def.card) do card[k]=v end
    card.region={15,1140,870,1260}
    local spec={name='dungeon_'..id,page=pages.features.list,axis='horizontal',view={15,1140,870,1260},
        valid=function() return pages.state():match('^list_')~=nil end,
        inspect=function()
            if pages.reward_claimed(id) then return {kind='claimed'} end
            if claimed_only then return nil end
            if pages.state()=='list_'..id then return {kind='selected'} end
            if detector.present(card) then return {kind='card',feature=card} end
        end}
    local match=list.find(ctx,spec)
    if not match or not list.activate(ctx,spec,match,'select_'..id) then return nil end
    if match.kind=='claimed' then return match end
    if not device.wait(function() return pages.state()=='list_'..id end,10) then return nil end
    return pages.reward_claimed(id) and {kind='claimed'} or {kind='selected'}
end
enter=function(ctx, id)
    local match=select_card(ctx,id)
    if not match then return result('blocked', 'target_card_not_found') end
    if match.kind=='claimed' then return audit_claimed(ctx,id) end
    local feature = pages.features.enter
    if not detector.present(feature) then feature=pages.features.continue end
    if not detector.present(feature) then return result('blocked', 'entry_button_not_verified') end
    act(ctx, feature, id .. '_enter')
    device.wait(function() return not pages.state():match('^list_') end, 10)
    if pages.state():match('^switch_') then
        if not switch_completed(ctx,id) then return result('blocked', 'cannot_abandon_unverified_dungeon') end
    end
    if not device.wait(function() return pages.state():match('^' .. id .. '_') end, 30) then
        return result('paused', 'entry_postcondition_not_verified')
    end
    return result('running', 'entered')
end
function M.verify_completed(ctx,id)
    if not ctx.identity_verified or ctx.config.business_date~=os.date('%Y%m%d') then return false end
    if not navigation.open_dungeon(ctx) or not device.wait(function()
        local s=pages.state()
        return s:match('^list_') or s:match('_done$') or s:match('_reward_sealed$')
    end,20) then return false end
    local state=pages.state()
    local prior=state:match('^(%w+)_done$') or state:match('^(%w+)_reward_sealed$')
    if prior and prior~=id then
        progress.write(ctx,prior,'done','completion_card_verified')
        if state==prior..'_reward_sealed' then
            act(ctx,pages.features.overview_back,'audit_leave_sealed_reward')
            if not device.wait(function() return pages.state()==prior..'_done' end,20) then return false end
        end
        act(ctx,pages.features.overview_back,'audit_return_dungeon_list')
        if not device.wait(function() return pages.state():match('^list_') end,20) then return false end
    end
    if pages.state():match('^list_') then
        local entered=enter(ctx,id)
        if entered.status=='done' then return navigation.return_home(ctx) end
        if entered.status~='running' then return false end
    end
    state=pages.state()
    if state~=id..'_done' and state~=id..'_reward_sealed' then return false end
    snapshot.capture(ctx,id..'_completion_audit','debug')
    progress.write(ctx,id,'done','completion_card_verified')
    return navigation.return_home(ctx)
end
local function execute(ctx, id)
    if cached_complete(ctx,id) then return result('done','runtime_completion_reused') end
    local state = pages.state()
    if detector.present(require('common.assets.home_dungeon')) then
        if not navigation.open_dungeon(ctx) or not device.wait(function()
            local landed=pages.state()
            return landed:match('^list_') or landed:match('^'..id..'_')
        end,20) then return result('paused','dungeon_entry_not_verified') end
        state=pages.state()
    end
    if state:match('^list_') then
        local entered=enter(ctx, id)
        if entered.status=='done' then return entered end
        if entered.status~='running' then return entered end
        state=pages.state()
    end
    if state==id .. '_ready' then
        local started=start(ctx,id)
        if started.status~='running' then return started end
    elseif state==id .. '_done' or state==id .. '_reward_sealed' then
        return finish(ctx,id)
    elseif state==id..'_active' then
        local resumed=resume_battle(ctx,id)
        if resumed.status~='running' then return resumed end
    elseif state~='battle' and state~='loading' then
        return result('blocked','active_dungeon_page_not_verified')
    end
    return wait_battles(ctx,id,false)
end
function M.run(ctx)
    assert(ctx.config.allow_reward_claim==false, 'reward claims forbidden in this implementation')
    local step, id = ctx.config.step, ctx.config.dungeon or 'wuji'
    assert(pages.definitions[id], 'unknown dungeon')
    if step=='daily' then
        assert(ctx.identity_verified, 'role identity must be verified')
        local outcomes={}
        for _, target in ipairs(ctx.config.dungeons or {'wuji','chechi'}) do
            if not cached_complete(ctx,target) then
                if detector.present(require('common.assets.home_dungeon')) then
                    if not navigation.open_dungeon(ctx) then return result('blocked','dungeon_list_not_opened') end
                    if not device.wait(function()
                        local landed=pages.state()
                        return landed:match('^list_') or landed:match('_done$') or landed:match('_reward_sealed$') or
                            landed==target..'_active' or landed==target..'_ready'
                    end,20) then
                        return result('paused','dungeon_list_not_verified')
                    end
                end
                local active=pages.state():match('^(%w+)_done$') or pages.state():match('^(%w+)_reward_sealed$')
                if active and active~=target then
                    local completed=finish(ctx,active)
                    if completed.status~='done' then return completed end
                    if not pages.state():match('^list_') then act(ctx,pages.features.overview_back,'return_list') end
                    if not device.wait(function() return pages.state():match('^list_') end,20) then
                        snapshot.capture(ctx,'dungeon_return_list_not_verified')
                        return result('paused','dungeon_return_list_not_verified')
                    end
                end
            end
            local outcome=execute(ctx,target)
            outcomes[target]=outcome
            log.write(ctx,'dungeon_result',target .. ' status=' .. outcome.status .. ' reason=' .. outcome.reason)
            if outcome.status~='done' then outcome.items=outcomes; return outcome end
        end
        return {status='done',reason=ctx.account.claim_dungeon_rewards==true and 'selected_dungeons_done_rewards_claimed' or 'selected_dungeons_done_rewards_unclaimed',items=outcomes}
    end
    M.observe(ctx)
    if step=='observe' then return result('paused','observation_only') end
    if step=='start' then return start(ctx,id) end
    if step=='complete' then return execute(ctx,id) end
    if step=='advance' then return wait_battles(ctx,id,true) end
    if step=='finish' then return finish(ctx,id) end
    if step=='enter' then
        return enter(ctx,id)
    end
    if step=='switch' then
        if not switch_completed(ctx,id) then return result('blocked','cannot_abandon_unverified_dungeon') end
        return result('paused','switched_without_claiming_reward')
    end
    if step=='select' then return result(select_card(ctx,id) and 'paused' or 'blocked','card_selection_only') end
    if step=='browse' and pages.state():match('^list_') then
        assert(device.swipe(ctx,pages.features.list,'dungeon_carousel',{750,1200},{200,1200}))
        return result('paused','carousel_observation_only')
    end
    if step=='back' and pages.state()==id .. '_done' then
        act(ctx,pages.features.overview_back,id .. '_return_list')
        return result('paused','returned_without_claiming_reward')
    end
    return result('blocked','unexpected_state_no_actions')
end
return M
