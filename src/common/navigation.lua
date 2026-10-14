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
    if not detector.present(picker) or not detector.present(selector) then return false end
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
                    local found=detector.find(f)
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
                    if not belongs or owners[belongs] then return false end
                    owners[belongs]=account.alias
                    matched=matched+1
                    signature[#signature+1]=account.alias..':'..found.x..':'..found.y
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
return_home=function(ctx)
    local pages = require('tasks.dungeon.pages')
    for _=1,4 do
        if detector.present(home) then return true end
        local state=pages.state()
        if detector.present(require('tasks.rewards.assets.discard_confirm')) then
            if not device.tap(ctx,require('tasks.rewards.assets.discard_cancel'),'cancel_gourd_discard_before_identity_check') then return false end
        elseif detector.present(require('tasks.rewards.assets.detail_title')) then
            if not device.tap(ctx,require('tasks.rewards.assets.detail_back'),'close_gourd_detail') or
                not device.wait(function() return detector.present(require('tasks.rewards.assets.inventory')) end,20) then return false end
        elseif detector.present(require('tasks.rewards.assets.inventory')) then
            if not device.tap(ctx,require('common.assets.home_tab'),'return_home_from_inventory') then return false end
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
            if gs=='quota_dialogue' then
                if not device.tap(ctx,ghost.features.quota_dialogue,'close_completed_ghost_dialogue') or
                    not device.wait(function() return ghost.state()=='task_list' or ghost.state()=='quota_completed_card' end,20) then return false end
            elseif gs=='task_list' or gs=='quota_completed_card' then
                if not device.tap(ctx,require('common.assets.home_tab'),'return_home_from_tasks') then return false end
            elseif gs=='ready_cost_three' or gs=='quota_idle' then
                if not device.tap(ctx,ghost.features.cancel,'close_idle_ghost_detail') then return false end
            else return false end
        end
    end
    return detector.present(home)
end
M.return_home=return_home
function M.prepare_recorded(ctx)
    -- Authentication is manual; this only enters the already selected saved role.
    require('common.screen').init(1)
    if detector.present(confirm) then
        if not device.tap(ctx, confirm, 'pocket_confirm') then return false end
    elseif detector.present(entry) then
        if not device.tap(ctx, entry, 'pocket_entry') then return false end
        if not device.wait(function() return detector.present(confirm) end, 20) then return false end
        if not device.tap(ctx, confirm, 'pocket_confirm') then return false end
    end
    require('common.screen').init(0)
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
        if not device.wait(function() return detector.present(home) and detector.present(identity) end,60) then
            log.write(ctx, 'account_blocked', 'saved_role_does_not_match_configured_identity')
            return false
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
