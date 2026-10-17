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
            return after=='inventory' or after=='discard_confirm' or
                (after=='detail' and detector.present(button))
        end,20) then return stop(ctx,'rewards_action_result_not_verified') end
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
