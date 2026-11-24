local pages=require('tasks.rewards.pages')
local detector=require('common.detector')
local device=require('common.device')
local navigation=require('common.navigation')
local progress=require('progress')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local list=require('common.list_navigation')
local dungeon_scope=require('tasks.dungeon.scope')
local M={}
local function result(status,reason) return {status=status,reason=reason} end
local function stop(ctx,reason,status)
    return {status=status or 'paused',reason=reason,failure_evidence=snapshot.capture(ctx,reason)}
end
function M.observe(ctx)
    log.write(ctx,'rewards_observe','state='..pages.state()..' no_actions=true')
end
local function verify_task_card(ctx,task)
    local task_pages=require('tasks.'..task..'.pages')
    local title=task_pages.features.task_list or task_pages.features.task_list_title
    if not device.tap(ctx,require('tasks.zhuagui.assets.home_tasks'),'rewards_verify_'..task) or
        not device.wait(function() return detector.present(title) end,20) then return false end
    local match=list.find(ctx,{name='rewards_'..task..'_completed',page=title,
        valid=function() return detector.present(title) end,
        inspect=function() if detector.present(task_pages.features.completed_card) then return {kind='completed'} end end})
    if not match then return false end
    log.write(ctx,'rewards_completion_audit',task..'_completed_card=true')
    snapshot.capture(ctx,'rewards_'..task..'_completed','debug')
    return navigation.return_home(ctx)
end
function M.verify_task_completed(ctx,task)
    if not ctx.identity_verified or ctx.config.business_date~=os.date('%Y%m%d') then return false end
    local record=progress.read(ctx,task)
    if record and record.status=='done' and record.stage=='completion_card_verified' then return true end
    if not verify_task_card(ctx,task) then return false end
    progress.write(ctx,task,'done','completion_card_verified')
    return true
end
function M.prerequisites(ctx)
    if not ctx.identity_verified then return false,'rewards_identity_not_verified' end
    if ctx.config.business_date~=os.date('%Y%m%d') then return false,'rewards_business_date_not_verified' end
    for _,task in ipairs({'shimen','zhuagui'}) do
        if not M.verify_task_completed(ctx,task) then return false,task..'_not_verified_complete' end
    end
    if dungeon_scope.completed(ctx) then return true end
    local targets,reason=dungeon_scope.resolve(ctx)
    if not targets then return false,reason end
    local automatic=dungeon_scope.automatic(ctx)
    local must_claim=automatic and ctx.account.claim_dungeon_rewards==true
    for _,id in ipairs(targets) do
        local record=progress.read(ctx,id) or dungeon_scope.item_cleared(ctx,id)
        if must_claim then
            if not (record and record.status=='done' and record.stage=='reward_claimed') then return false,id..'_reward_not_verified' end
        elseif not (record and record.status=='done' and ({completion_card_verified=true,reward_claimed=true,reward_intentionally_unclaimed=true})[record.stage]) then
            if not require('tasks.dungeon.task').verify_completed(ctx,id) then return false,id..'_not_verified_complete' end
        end
    end
    if automatic then
        dungeon_scope.mark_complete(ctx)
        if not dungeon_scope.completed(ctx) then return false,'dungeon_scope_completion_not_saved' end
    end
    return true
end
function M.run(ctx)
    if ctx.config.step=='observe' then M.observe(ctx);return result('paused','observation_only') end
    if not ctx.config.business_date or ctx.config.business_date~=os.date('%Y%m%d') then return stop(ctx,'rewards_business_date_not_verified','blocked') end
    if not ctx.identity_verified and not navigation.prepare_recorded(ctx) then return stop(ctx,'rewards_identity_not_verified','blocked') end
    if ctx.config.rewards_debug_after_shimen then
        if ctx.config.step=='daily' or ctx.config.task~='rewards' then return stop(ctx,'rewards_debug_scope_invalid','blocked') end
        if not verify_task_card(ctx,'shimen') then return stop(ctx,'rewards_shimen_completed_card_not_verified','blocked') end
    else
        local ok,reason=M.prerequisites(ctx)
        if not ok then return stop(ctx,reason,'blocked') end
    end
    local opened,reason=pages.open_treasury(ctx)
    if not opened then return stop(ctx,reason) end
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
        snapshot.capture(ctx,'rewards_inventory_observed','evidence')
        return result('paused','rewards_inventory_observed')
    end
    if not ({complete=true,daily=true,advance=true})[ctx.config.step] then return stop(ctx,'rewards_step_invalid','blocked') end
    for _,name in ipairs({'task','dungeon','special'}) do
        local outcome=require('tasks.rewards.inventory').clear(ctx,name)
        if outcome.status~='done' then return outcome end
    end
    if not navigation.return_home(ctx) then return stop(ctx,'rewards_return_home_not_verified') end
    local stage=ctx.config.rewards_debug_after_shimen and 'debug_inventory_empty' or 'daily_inventory_empty'
    progress.write(ctx,'rewards','done',stage)
    log.write(ctx,'rewards_complete','task_empty=true dungeon_empty=true special_empty=true')
    return result('done',stage)
end
return M
