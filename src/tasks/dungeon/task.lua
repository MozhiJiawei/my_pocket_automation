local log = require('dfx.log')
local pages = require('tasks.dungeon.pages')
local device = require('common.device')
local progress = require('progress')
local detector = require('common.detector')
local snapshot = require('dfx.snapshot')
local navigation = require('common.navigation')
local M = {}
local function result(status, reason) return {status=status, reason=reason} end
local function act(ctx, feature, label)
    assert(device.tap(ctx, feature, label), 'action_target_disappeared:' .. label)
end
function M.observe(ctx)
    log.write(ctx, 'dungeon_observe', 'state=' .. pages.state() .. ' no_actions=true')
end
local function start(ctx, id)
    if pages.state() ~= id .. '_ready' then return result('blocked', 'ready_page_not_verified') end
    if progress.read(ctx, id) then return result('blocked', 'daily_start_already_recorded') end
    progress.write(ctx, id, 'running', 'start_requested')
    act(ctx, pages.features.start, id .. '_start')
    return result('running', 'start_requested')
end
local function switch_completed(ctx)
    local previous = progress.read(ctx, 'wuji')
    if not previous or previous.status ~= 'done' then return false end
    if pages.state() ~= 'switch_wuji_chechi' then return false end
    act(ctx, pages.features.switch_wuji_chechi, 'switch_after_verified_completion')
    return true
end
local function finish(ctx, id)
    local state = pages.state()
    if state ~= id .. '_done' and state ~= id .. '_reward_sealed' then
        return result('blocked', 'completion_not_verified')
    end
    snapshot.capture(ctx, id .. '_completion_evidence')
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
local function wait_battles(ctx, id, stop_after_battle)
    local deadline, unknown_since, last_state = os.time()+(ctx.config.dungeon_timeout or 1800), nil, nil
    local heartbeat = os.time()
    while os.time() < deadline do
        local state = pages.state()
        if state ~= last_state then log.write(ctx, 'state', id .. ' ' .. state); last_state=state end
        if state == id .. '_reward_sealed' or state == id .. '_done' then
            if stop_after_battle then snapshot.capture(ctx, 'next_state'); return result('paused', 'battle_completed') end
            return finish(ctx, id)
        elseif state == 'battle' then
            unknown_since = nil
            if detector.present(pages.features.speed_one) then act(ctx, pages.features.speed_one, 'battle_speed') end
        elseif state == 'loading' then
            unknown_since = nil
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
            snapshot.capture(ctx, 'waiting')
            heartbeat=os.time()
        end
        mSleep(1000)
    end
    snapshot.capture(ctx, 'timeout')
    return result('failed', 'dungeon_timeout')
end
local function select_card(ctx, id)
    local def = assert(pages.definitions[id])
    local card = {}
    for k,v in pairs(def.card) do card[k]=v end
    card.region={15,1140,870,1260}
    for pass=1,2 do
        for i=1,5 do
            if not pages.state():match('^list_') then return false end
            if pages.state() == 'list_' .. id then return true end
            if detector.present(card) then
                act(ctx, card, 'select_' .. id)
                return device.wait(function() return pages.state()=='list_' .. id end, 10)
            end
            local from, to = {750,1200}, {200,1200}
            if pass==2 then from,to=to,from end
            if not device.swipe(ctx, pages.features.list, 'find_' .. id, from, to) then return false end
        end
    end
    return false
end
local function enter(ctx, id)
    if not select_card(ctx, id) then return result('blocked', 'target_card_not_found') end
    local feature = pages.features.enter
    if not detector.present(feature) then feature=pages.features.continue end
    if not detector.present(feature) then return result('blocked', 'entry_button_not_verified') end
    act(ctx, feature, id .. '_enter')
    device.wait(function() return not pages.state():match('^list_') end, 10)
    if pages.state() == 'switch_wuji_chechi' then
        if id~='chechi' or not switch_completed(ctx) then return result('blocked', 'cannot_abandon_unverified_dungeon') end
    end
    if not device.wait(function() return pages.state():match('^' .. id .. '_') end, 30) then
        return result('paused', 'entry_postcondition_not_verified')
    end
    return result('running', 'entered')
end
local function execute(ctx, id)
    local existing = progress.read(ctx, id)
    if existing and existing.status=='done' then
        log.write(ctx, 'daily_skip', id .. ' completion_record_present')
        return result('done', 'daily_done_skip')
    end
    local state = pages.state()
    if state:match('^list_') then
        local entered=enter(ctx, id)
        if entered.status~='running' then return entered end
        state=pages.state()
    end
    if state==id .. '_ready' then
        local started=start(ctx,id)
        if started.status~='running' then return started end
    elseif state==id .. '_done' or state==id .. '_reward_sealed' then
        return finish(ctx,id)
    elseif not existing then
        return result('blocked','active_dungeon_ownership_not_recorded')
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
        for _, target in ipairs({'wuji','chechi'}) do
            local record=progress.read(ctx,target)
            if not record or record.status~='done' then
                if detector.present(require('common.assets.home_dungeon')) then
                    if not navigation.open_dungeon(ctx) then return result('blocked','dungeon_list_not_opened') end
                    if not device.wait(function() return pages.state():match('^list_') end,20) then
                        return result('paused','dungeon_list_not_verified')
                    end
                end
                local active=pages.state():match('^(%w+)_done$')
                if active and active~=target then act(ctx,pages.features.overview_back,'return_list') end
            end
            local outcome=execute(ctx,target)
            outcomes[target]=outcome
            log.write(ctx,'dungeon_result',target .. ' status=' .. outcome.status .. ' reason=' .. outcome.reason)
            if outcome.status~='done' then outcome.items=outcomes; return outcome end
        end
        return {status='done',reason='both_dungeons_done_rewards_unclaimed',items=outcomes}
    end
    M.observe(ctx)
    if step=='observe' then return result('paused','observation_only') end
    if step=='start' then return start(ctx,id) end
    if step=='complete' then return execute(ctx,id) end
    if step=='advance' then return wait_battles(ctx,id,true) end
    if step=='finish' then return finish(ctx,id) end
    if step=='enter' then
        local record=progress.read(ctx,id)
        if record and record.status=='done' then return result('done','daily_done_skip') end
        return enter(ctx,id)
    end
    if step=='switch' then
        if id~='chechi' or not switch_completed(ctx) then return result('blocked','cannot_abandon_unverified_dungeon') end
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
