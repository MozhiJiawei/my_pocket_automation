-- Observation only: retry the existing puzzle, scroll, and save every page.
local pages=require('tasks.zhuagui.pages')
local device=require('common.device')
local snapshot=require('dfx.snapshot')
local log=require('dfx.log')
local M={}
function M.collect(ctx)
    local rounds=ctx.config.browse_rounds or 1
    if type(rounds)~='number' or rounds%1~=0 or rounds<1 or rounds>60 then
        return {status='blocked',reason='invalid_catalog_rounds'}
    end
    for round=1,rounds do
        for _=1,6 do
            local state=pages.state()
            if state=='find' then break end
            local feature=({retry=pages.features.retry,dialogue=pages.features.dialogue_next,depart=pages.features.depart})[state]
            if not feature then return {status='paused',reason='catalog_prepare_not_verified'} end
            if not device.tap(ctx,feature,'catalog_prepare_'..round..'_'..state) then
                return {status='paused',reason='catalog_retry_changed'}
            end
            if not device.wait(function()
                local next_state=pages.state()
                return next_state~=state and ({find=true,retry=true,dialogue=true,depart=true})[next_state]
            end,6) then
                return {status='paused',reason='catalog_prepare_changed'}
            end
        end
        if not device.wait(function() return pages.state()=='find' end,10) then
            return {status='paused',reason='catalog_find_not_open'}
        end
        local prefix=string.format('catalog_r%03d_',round)
        log.write(ctx,'catalog_round','round=' .. round .. ' candidate_taps=0 new_accepts=0')
        snapshot.capture(ctx,prefix .. 'p01')
        local captured=1
        for page=2,7 do
            -- The previous page is already the before evidence; capture each new page once.
            if not device.swipe(ctx,pages.features.find_title,prefix .. 'scroll_' .. page,{730,1350},{730,750},
                {capture_before=false,capture_after=false,settle_ms=350}) then
                snapshot.capture(ctx,prefix .. 'incomplete')
                if pages.state()=='retry' then break end
                return {status='paused',reason='catalog_page_changed'}
            end
            if pages.state()~='find' then
                snapshot.capture(ctx,prefix .. 'incomplete')
                if pages.state()=='retry' then break end
                return {status='paused',reason='catalog_page_changed'}
            end
            snapshot.capture(ctx,prefix .. string.format('p%02d',page))
            captured=page
        end
        log.write(ctx,'catalog_round_done','round=' .. round .. ' pages=' .. captured .. ' candidate_taps=0')
        if round<rounds and not device.wait(function() return ({retry=true,dialogue=true,depart=true})[pages.state()] end,45,500) then
            snapshot.capture(ctx,prefix .. 'retry_missing')
            return {status='paused',reason='catalog_retry_not_observed'}
        end
    end
    return {status='paused',reason='find_catalog_observation_only'}
end
return M
