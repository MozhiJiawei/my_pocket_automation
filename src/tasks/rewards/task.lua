local pages=require('tasks.rewards.pages')
local detector=require('common.detector')
local device=require('common.device')
local navigation=require('common.navigation')
local progress=require('progress')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local M={}
local function result(status,reason) return {status=status,reason=reason} end
local function stop(ctx,reason,status)
    snapshot.capture(ctx,reason)
    return result(status or 'paused',reason)
end
function M.observe(ctx)
    log.write(ctx,'rewards_observe','state='..pages.state()..' no_actions=true')
end
local function verify_shimen_card(ctx)
    local shimen=require('tasks.shimen.pages')
    if not device.tap(ctx,require('tasks.zhuagui.assets.home_tasks'),'rewards_verify_shimen') or
        not device.wait(function() return detector.present(shimen.features.task_list) end,20) then return false end
    for i=0,4 do
        if detector.present(shimen.features.completed_card) then
            log.write(ctx,'rewards_debug_gate','shimen_completed_card=true')
            snapshot.capture(ctx,'rewards_shimen_completed','debug')
            return navigation.return_home(ctx)
        end
        if i<4 and not device.swipe(ctx,shimen.features.task_list,'rewards_find_shimen_completed',{800,1260},{800,600}) then return false end
    end
    return false
end
function M.prerequisites(ctx)
    local s=progress.read(ctx,'shimen')
    if not s or s.status~='done' or s.attempts~=20 or s.completed_count~=20 or s.carryover_pending==1 or
        not ({delivery_verified=true,completion_card_verified=true,one_task_completed=true})[s.stage] then return false,'shimen_not_verified_complete' end
    local z=progress.read(ctx,'zhuagui')
    if not z or z.status~='done' or z.attempts~=25 or z.completed_count~=25 or z.stage~='all_25_completed_gourds_unopened' then return false,'zhuagui_not_verified_complete' end
    for _,id in ipairs(ctx.config.dungeons or {'wuji','chechi'}) do
        local d=progress.read(ctx,id)
        if not d or d.status~='done' or not ({reward_intentionally_unclaimed=true,reward_claimed=true})[d.stage] then return false,id..'_not_verified_complete' end
    end
    return true
end
function M.run(ctx)
    if ctx.config.step=='observe' then M.observe(ctx);return result('paused','observation_only') end
    if not ctx.config.business_date or ctx.config.business_date~=os.date('%Y%m%d') then return stop(ctx,'rewards_business_date_not_verified','blocked') end
    if not navigation.prepare_recorded(ctx) then return stop(ctx,'rewards_identity_not_verified','blocked') end
    if ctx.config.rewards_debug_after_shimen then
        if ctx.config.step=='daily' or ctx.config.task~='rewards' then return stop(ctx,'rewards_debug_scope_invalid','blocked') end
        if not verify_shimen_card(ctx) then return stop(ctx,'rewards_shimen_completed_card_not_verified','blocked') end
    else
        local ok,reason=M.prerequisites(ctx)
        if not ok then return stop(ctx,reason,'blocked') end
    end
    local bag={}
    for k,v in pairs(require('common.assets.home_dungeon')) do bag[k]=v end
    bag.tap_offset={bag.tap_offset[1]+116,bag.tap_offset[2]+817}
    if not device.tap(ctx,bag,'rewards_open_inventory') or
        not device.wait(function() return pages.state()=='inventory' end,20) then return stop(ctx,'rewards_inventory_entry_not_verified') end
    if not detector.present(pages.features.task_tab) then
        if not device.tap(ctx,pages.features.treasury_tab,'rewards_open_treasury') or
            not device.wait(function() return detector.present(pages.features.task_tab) end,20) then return stop(ctx,'rewards_treasury_not_verified') end
    end
    local category=ctx.config.rewards_inspect_category or 'task'
    if category~='task' and (not ctx.config.rewards_debug_after_shimen or not ({enter=true,browse=true})[ctx.config.step]) then
        return stop(ctx,'rewards_inspection_scope_invalid','blocked')
    end
    if ctx.config.step=='enter' or ctx.config.step=='browse' then
        if not pages.select_category(ctx,category) then return stop(ctx,'rewards_category_not_verified') end
        if ctx.config.step=='browse' and not pages.empty_category() then
            local cards=pages.cards()
            if not cards or not cards[1] or not device.tap(ctx,cards[1],'rewards_inspect_gourd') then return stop(ctx,'rewards_gourd_entry_not_verified') end
        end
        snapshot.capture(ctx,'rewards_inventory_observed')
        return result('paused','rewards_inventory_observed')
    end
    if not ({complete=true,daily=true,advance=true})[ctx.config.step] then return stop(ctx,'rewards_step_invalid','blocked') end
    for _,name in ipairs({'task','dungeon','special'}) do
        local outcome=require('tasks.rewards.inventory').clear(ctx,name)
        if outcome.status~='done' then return outcome end
    end
    if not navigation.prepare_recorded(ctx) then return stop(ctx,'rewards_return_home_not_verified') end
    local stage=ctx.config.rewards_debug_after_shimen and 'debug_inventory_empty' or 'daily_inventory_empty'
    progress.write(ctx,'rewards','done',stage)
    log.write(ctx,'rewards_complete','task_empty=true dungeon_empty=true special_empty=true')
    return result('done',stage)
end
return M
