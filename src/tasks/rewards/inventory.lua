local pages=require('tasks.rewards.pages')
local detector=require('common.detector')
local device=require('common.device')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local M={}
local function result(status,reason) return {status=status,reason=reason} end
local function stop(ctx,reason)
    return {status='paused',reason=reason,failure_evidence=snapshot.capture(ctx,reason)}
end
-- The caller has verified today's ghost completion and returned to this role's home.
function M.ghost_count(ctx)
    local navigation=require('common.navigation')
    local list=require('common.list_navigation')
    local function same_day() return ctx.config.business_date==os.date('%Y%m%d') end
    if not same_day() then return nil,'ghost_gourd_business_date_not_verified' end
    if not ctx.identity_verified or not navigation.home_identity_matches(ctx) then
        return nil,'ghost_gourd_identity_not_verified'
    end
    local opened,reason=pages.open_treasury(ctx)
    if not opened then return nil,reason end
    if not pages.select_category(ctx,'task') then return nil,'ghost_gourd_task_category_not_verified' end
    if pages.empty_category() then return nil,'ghost_gourd_missing' end
    local feature=pages.features.ghost_gourd_card
    local spec={name='ghost_gourd',page=pages.features.task_tab_selected,view={50,418,849,1258},
        valid=function()
            return same_day() and pages.state()=='inventory' and detector.present(pages.features.task_tab_selected)
        end,
        inspect=function()
            if detector.present(feature) then return {kind='ghost_gourd',feature=feature} end
        end}
    local match,search_reason=list.find(ctx,spec)
    if not match then return nil,'ghost_gourd_'..search_reason end
    if not list.activate(ctx,spec,match,'rewards_inspect_ghost_gourd') then
        return nil,'ghost_gourd_entry_not_verified'
    end
    local count
    if not device.wait(function()
        count=pages.ghost_gourd_count()
        return count~=nil
    end,20) then return nil,'ghost_gourd_count_not_verified' end
    if not navigation.return_home(ctx) then return nil,'ghost_gourd_return_home_not_verified' end
    if not device.wait(function() return navigation.home_identity_matches(ctx) end,20) then
        return nil,'ghost_gourd_identity_not_verified'
    end
    if not same_day() then return nil,'ghost_gourd_business_date_not_verified' end
    return count
end
function M.clear(ctx,category)
    if not pages.select_category(ctx,category) then return stop(ctx,'rewards_category_not_verified') end
    local discard=category=='special'
    local button=discard and pages.features.discard or pages.features.open_one
    -- Process the first remaining gourd until its row disappears, then the next.
    for _=1,200 do
        local state=pages.state()
        if state=='inventory' then
            if pages.empty_category() then
                snapshot.capture(ctx,'rewards_'..category..'_empty','debug')
                log.write(ctx,'rewards_category_empty','category='..category)
                return result('done','category_empty')
            end
            local cards=pages.cards()
            if not cards or not cards[1] or not device.tap(ctx,cards[1],'rewards_inspect_gourd') or
                not device.wait(function() return pages.state()=='detail' end,20) then
                return stop(ctx,'rewards_gourd_entry_not_verified')
            end
        elseif state~='detail' then return stop(ctx,'rewards_page_not_verified') end
        if not device.tap(ctx,button,discard and 'rewards_discard' or 'rewards_open') then return stop(ctx,'rewards_action_not_verified') end
        if not device.wait(function()
            local after=pages.state()
            return after=='inventory' or after=='discard_confirm' or (not discard and after=='bonus_receipt') or
                (after=='detail' and detector.present(button))
        end,20) then return stop(ctx,'rewards_action_result_not_verified') end
        if pages.state()=='bonus_receipt' and not pages.close_receipt(ctx) then
            return stop(ctx,'rewards_bonus_receipt_not_closed')
        end
        if pages.state()=='discard_confirm' then
            if not discard or not device.tap(ctx,pages.features.discard_confirm,'rewards_confirm_discard') or
                not device.wait(function() return pages.state()=='detail' or pages.state()=='inventory' end,20) then
                return stop(ctx,'rewards_discard_confirmation_not_verified')
            end
        end
        if ctx.config.step=='advance' then return result('paused',discard and 'discarded_one_special' or 'opened_one_gourd') end
    end
    return stop(ctx,'rewards_loop_limit_reached')
end
return M
