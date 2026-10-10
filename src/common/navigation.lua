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
local function return_home(ctx)
    local pages = require('tasks.dungeon.pages')
    for _=1,4 do
        if detector.present(home) then return true end
        local state=pages.state()
        if state:match('^list_') then
            if not device.tap(ctx,pages.features.list_back,'return_home') then return false end
        elseif state:match('_done$') or state:match('_ready$') then
            if not device.tap(ctx,pages.features.overview_back,'return_dungeon_list') then return false end
        else
            return false
        end
    end
    return detector.present(home)
end
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
