local detector = require('common.detector')
local device = require('common.device')
local log = require('dfx.log')
local M = {}
local home = require('common.assets.home_dungeon')
local entry = require('common.assets.pocket_entry')
local confirm = require('common.assets.pocket_confirm')
local picker = require('common.assets.saved_account_picker')
local switch = require('common.assets.saved_account_switch')
local current_marker = require('common.assets.current_role_marker')
local return_home
local function select_saved(ctx)
    local selector_path='/storage/emulated/0/TouchSprite/res/daily_selector_' .. ctx.account.alias .. '.lua'
    local load_selector=loadfile(selector_path)
    if not load_selector then return false end
    local selector=load_selector()
    if not detector.present(picker) then return false end
    if not detector.present(selector) then
        local match=require('common.list_navigation').find(ctx,{name='saved_role_'..ctx.account.alias,
            page=picker,view={35,330,850,1380},max_forward=6,
            valid=function() return detector.present(picker) end,
            inspect=function() if detector.present(selector) then return {kind='role'} end end})
        if not match then return false end
    end
    if detector.present(current_marker) then
        -- Only use the current marker when it belongs to the same calibrated tile.
        local selected, marker = detector.find(selector), detector.find(current_marker)
        if math.abs(selected.x-marker.x)<220 and selected.y>marker.y and selected.y-marker.y<260 then
            local back=require('tasks.dungeon.assets.overview_back')
            return device.tap(ctx,back,'close_current_saved_role_picker')
        end
    end
    return device.tap(ctx,selector,'select_saved_role')
end
-- Onboarding only: enter one reviewed saved tile and capture its home identity.
-- No daily task is allowed until a separately calibrated home identity matches.
function M.inspect_saved(ctx)
    require('common.screen').init(0)
    if not detector.present(picker) then
        if not detector.present(home) or not device.tap(ctx,switch,'inspect_saved_role_picker') or
            not device.wait(function() return detector.present(picker) end,20) then return false end
    end
    if not select_saved(ctx) then return false end
    -- The old home can remain visible while a role change is in flight.
    mSleep(5000)
    return device.wait(function() return detector.present(home) and not detector.present(picker) end,60)
end
local function selector_for(account)
    local loader=loadfile('/storage/emulated/0/TouchSprite/res/daily_selector_'..account.alias..'.lua')
    return loader and loader() or nil
end
function M.verify_roster(ctx)
    require('common.screen').init(0)
    if not detector.present(picker) then
        ctx.account=ctx.config.accounts[1]
        if not M.prepare_recorded(ctx) then return false end
        if not device.tap(ctx,switch,'open_roster_picker') or
            not device.wait(function() return detector.present(picker) end,20) then return false end
    end
    local seen,last,scrolls={},nil,0
    local tile=require('common.assets.saved_role_tile')
    local selected_tile=require('common.assets.saved_role_current_tile')
    for page=1,7 do
        if not detector.present(picker) then return false end
        local anchors
        local matched,owners,signature=0,{},{}
        local readable=device.wait(function()
            if not detector.present(picker) then return false end
            anchors={}
            for _,range in ipairs({{150,300},{545,700}}) do
                local top=330
                for _=1,6 do
                    local f={}; for k,v in pairs(tile) do f[k]=v end
                    f.region={range[1],top,range[2],1340}
                    local selected={};for k,v in pairs(selected_tile) do selected[k]=v end
                    selected.region=f.region
                    local found=detector.find(f)
                    local marked=detector.find(selected)
                    if marked and (not found or marked.y<found.y) then found=marked end
                    if not found then break end
                    anchors[#anchors+1]=found
                    top=found.y+100
                end
            end
            matched,owners,signature=0,{},{}
            for _,account in ipairs(ctx.config.accounts) do
                local selector=selector_for(account)
                if not selector then return false end
                local found=detector.find(selector)
                if found then
                    local belongs=nil
                    for index,anchor in ipairs(anchors) do
                        if math.abs(found.x-anchor.x)<220 and found.y-anchor.y>110 and found.y-anchor.y<240 then belongs=index end
                    end
                    if not belongs or owners[belongs] then
                        log.write(ctx,'roster_match_blocked','alias='..account.alias..' x='..found.x..' y='..found.y..' tile='..tostring(belongs))
                        return false
                    end
                    owners[belongs]=account.alias
                    matched=matched+1
                    signature[#signature+1]=account.alias..':'..found.x..':'..found.y
                else
                    log.write(ctx,'roster_not_visible',account.alias)
                end
            end
            return #anchors>0 and matched==#anchors
        end,10,500)
        log.write(ctx,'roster_counts','page='..page..' tiles='..#anchors..' matched='..matched)
        if not readable then
            log.write(ctx,'roster_blocked','unconfigured_or_partial_role_tile')
            return false
        end
        for _,alias in pairs(owners) do seen[alias]=true end
        table.sort(signature)
        local fingerprint=table.concat(signature,'|')
        if fingerprint==last then
            for _,account in ipairs(ctx.config.accounts) do if not seen[account.alias] then return false end end
            for _=1,scrolls do
                if not device.swipe(ctx,picker,'restore_roster_top',{780,560},{780,1200}) then return false end
            end
            if not device.tap(ctx,require('tasks.dungeon.assets.overview_back'),'close_verified_roster') then return false end
            log.write(ctx,'roster_verified','roles='..#ctx.config.accounts)
            return device.wait(function() return detector.present(home) end,20)
        end
        last=fingerprint
        if not device.swipe(ctx,picker,'scan_saved_roster',{780,1200},{780,560}) then return false end
        scrolls=scrolls+1
    end
    return false
end
function M.dismiss_overlays(ctx)
    local rewards=require('tasks.rewards.pages')
    if rewards.features and rewards.features.bonus_receipt and detector.present(rewards.features.bonus_receipt) then
        if not rewards.close_receipt(ctx) then
            log.write(ctx,'account_blocked','rewards_bonus_receipt_not_closed');return false
        end
    end
    for _,spec in ipairs({{'incident_notice','close_incident_notice'},{'chat_expanded','collapse_chat'}}) do
        local feature=require('common.assets.'..spec[1])
        if detector.present(feature) then
            if not device.tap(ctx,feature,spec[2]) or
                not device.wait(function() return not detector.present(feature) end,10) then
                log.write(ctx,'account_blocked',spec[1]..'_not_closed');return false
            end
        end
    end
    return true
end
return_home=function(ctx)
    local pages = require('tasks.dungeon.pages')
    for _=1,4 do
        if not M.dismiss_overlays(ctx) then return false end
        if detector.present(require('common.assets.settings_page')) then
            if not device.tap(ctx,require('common.assets.settings_back'),'return_home_from_settings') or
                not device.wait(function() return detector.present(home) end,20) then return false end
        end
        if detector.present(home) then return true end
        local state=pages.state()
        log.write(ctx,'navigation_state','return_home dungeon='..state)
        if detector.present(require('tasks.rewards.assets.discard_confirm')) then
            if not device.tap(ctx,require('tasks.rewards.assets.discard_cancel'),'cancel_gourd_discard_before_identity_check') then return false end
        elseif detector.present(require('tasks.rewards.assets.detail_title')) then
            if not device.tap(ctx,require('tasks.rewards.assets.detail_back'),'close_gourd_detail') or
                not device.wait(function() return detector.present(require('tasks.rewards.assets.inventory')) end,20) then return false end
        elseif detector.present(require('tasks.rewards.assets.inventory')) then
            if not device.tap(ctx,require('common.assets.home_tab'),'return_home_from_inventory') then return false end
        elseif state:match('_claim_receipt$') then
            if not device.wait(function()
                return detector.present(pages.features.claim_receipt_close) or not pages.state():match('_claim_receipt$')
            end,20,300) then return false end
            if pages.state():match('_claim_receipt$') and
                not device.tap(ctx,pages.features.claim_receipt_close,'close_claim_receipt_before_identity_check') and
                pages.state():match('_claim_receipt$') then return false end
            if not device.wait(function() return not pages.state():match('_claim_receipt$') end,20) then return false end
        elseif state:match('_claim_confirm$') then
            if not device.tap(ctx,pages.features.claim_cancel,'cancel_claim_before_identity_check') or
                not device.wait(function() return pages.state():match('_reward_sealed$') end,20) then return false end
        elseif state:match('^switch_') then
            local feature={}
            for k,v in pairs(pages.features[state]) do feature[k]=v end
            feature.tap_offset={feature.tap_offset[1]-390,feature.tap_offset[2]}
            if not device.tap(ctx,feature,'cancel_dungeon_switch') then return false end
            if not device.wait(function() return pages.state():match('^list_') end,20) then return false end
        elseif state:match('^list_') then
            if not device.tap(ctx,pages.features.list_back,'return_home') then return false end
        elseif state:match('_done$') or state:match('_ready$') or state:match('_reward_sealed$') then
            if not device.tap(ctx,pages.features.overview_back,'return_dungeon_list') then return false end
        else
            local ghost=require('tasks.zhuagui.pages')
            local gs=ghost.state()
            log.write(ctx,'navigation_state','return_home ghost='..gs)
            local shimen=require('tasks.shimen.pages')
            local ss=shimen.state()
            if ss=='puzzle_retry' or ss=='ready' then
                local back=ss=='puzzle_retry' and require('tasks.shimen.assets.rest_back') or shimen.features.back
                if not device.tap(ctx,back,'shimen_rest_before_identity_check',function()
                    return shimen.state()==ss
                end) or not device.wait(function()
                    local state=shimen.state()
                    return state=='task_list' or state=='completed_card' or state=='home' or state=='catch' or state=='go'
                end,20) then return false end
            elseif ss=='catch' or ss=='go' then
                if not device.tap(ctx,require('common.assets.home_tab'),'shimen_home_without_cancel',function()
                    return shimen.state()==ss
                end) or not device.wait(function() return detector.present(home) end,20) then return false end
            elseif gs=='quota_dialogue' then
                if not device.tap(ctx,ghost.features.quota_dialogue,'close_completed_ghost_dialogue') or
                    not device.wait(function() return ghost.state()=='task_list' or ghost.state()=='quota_completed_card' end,20) then return false end
            elseif gs=='task_list' or gs=='quota_completed_card' then
                if not device.tap(ctx,require('common.assets.home_tab'),'return_home_from_tasks') then
                    log.write(ctx,'account_blocked','home_tab_not_verified');return false
                end
            elseif gs=='ready_cost_three' or gs=='quota_idle' then
                if not device.tap(ctx,ghost.features.cancel,'close_idle_ghost_detail') then return false end
            else return false end
        end
    end
    return detector.present(home)
end
M.return_home=return_home
local function enter_pocket(ctx,restarted)
    local screen=require('common.screen')
    -- A restarted game changes from portrait Pocket to landscape login.
    screen.init(1,restarted)
    local function finish(ok,reason)
        screen.init(0)
        if reason then log.write(ctx,'account_blocked',reason) end
        return ok
    end
    local action,observed=nil,false
    local entered=device.wait(function()
        for _,target in ipairs({{confirm,'pocket_confirm'},{entry,'pocket_entry'}}) do
            if detector.present(target[1]) then
                observed=true
                -- A false tap sent no input: the animated target changed during
                -- revalidation. Wait for it again; never repeat a sent tap.
                if device.tap(ctx,target[1],target[2]) then action=target[2];return true end
            end
        end
        return false
    end,restarted and 360 or 1)
    if not entered then
        if restarted or observed then return finish(false,'pocket_entry_not_actionable') end
        return finish(true)
    end
    if action=='pocket_entry' and not device.wait(function()
        return detector.present(confirm) and device.tap(ctx,confirm,'pocket_confirm')
    end,20) then
        return finish(false,'pocket_confirmation_not_verified')
    end
    -- Confirmation rotates Android after the tap returns. Refresh the capture
    -- while waiting, so a stale landscape stride cannot drive home navigation.
    if not device.wait(function()
        screen.init(0,true)
        -- The lower home landmark can appear before Android finishes rotating.
        -- Require the upper role control too before using portrait coordinates.
        return (detector.present(home) and detector.present(switch)) or detector.present(picker)
    end,60) then
        return finish(false,'pocket_home_not_verified')
    end
    return finish(true)
end
local function restart_pocket(ctx)
    log.write(ctx,'entry_recovery','restart_game_for_saved_role')
    closeApp('com.netease.mhxyhtb')
    mSleep(1500)
    runApp('com.netease.mhxyhtb')
    mSleep(8000)
    return enter_pocket(ctx,true)
end
function M.prepare_recorded(ctx)
    -- Authentication is manual; this only enters the already selected saved role.
    require('common.screen').init(0)
    if detector.present(require('common.assets.settings_page')) and not return_home(ctx) then
        if not restart_pocket(ctx) then return false end
    elseif not enter_pocket(ctx,false) then return false end
    -- Entering Pocket may briefly show the picker while the saved role loads.
    if detector.present(picker) and not device.wait(function() return detector.present(home) end,10) then
        if not select_saved(ctx) then return false end
    end
    return_home(ctx)
    if not device.wait(function() return detector.present(home) end, 60) then
        log.write(ctx, 'account_blocked', 'home_not_verified')
        return false
    end
    local identity_path = '/storage/emulated/0/TouchSprite/res/daily_identity_' .. ctx.account.alias .. '.lua'
    local identity = assert(loadfile(identity_path))()
    if not detector.present(identity) then
        if not device.tap(ctx,switch,'open_saved_role_picker') then return false end
        if not device.wait(function() return detector.present(picker) end,10) or not select_saved(ctx) then
            log.write(ctx,'account_blocked','configured_saved_role_not_found')
            return false
        end
        if not device.wait(function() return detector.present(home) and detector.present(identity) end,10) then
            -- The saved-role picker can update the login selection while the
            -- Pocket home retains the previous session. Re-enter once, then
            -- require the real home identity before accepting any task.
            if not detector.present(home) or not restart_pocket(ctx) or
                not device.wait(function() return detector.present(home) and detector.present(identity) end,60) then
                log.write(ctx, 'account_blocked', 'saved_role_does_not_match_configured_identity')
                return false
            end
        end
    end
    ctx.identity_verified = true
    log.write(ctx, 'account_verified', ctx.account.alias)
    return true
end
function M.finish_account(ctx)
    return return_home(ctx)
end
function M.open_dungeon(ctx)
    if not ctx.identity_verified then return false end
    return device.tap(ctx, home, 'open_dungeon_list')
end
return M
