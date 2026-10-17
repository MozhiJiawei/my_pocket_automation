-- Observation only: retry the existing puzzle, scroll, and save every page.
local pages=require('tasks.zhuagui.pages')
local device=require('common.device')
local snapshot=require('dfx.snapshot')
local log=require('dfx.log')
local M={}
-- Normalize a live question without touching answers or opening another round.
function M.question_key()
    -- Exclude the countdown bar and selected-item counter.
    return require('common.list_navigation').fingerprint({60,335,580,420})
end
function M.to_top(ctx,question,expected_first)
    local fingerprint=require('common.list_navigation').fingerprint
    local view={60,535,840,1405}
    question=question or M.question_key()
    local unchanged=0
    for attempt=1,12 do
        if pages.state()~='find' or M.question_key()~=question then return nil,'catalog_question_changed' end
        local before=fingerprint(view)
        local x=attempt%2==0 and 810 or 730
        if not device.swipe(ctx,pages.features.find_title,'catalog_to_top',{x,750},{x,1350},
            {capture_before=false,capture_after=false,settle_ms=350}) then return nil,'catalog_scroll_not_verified' end
        if pages.state()~='find' or M.question_key()~=question then return nil,'catalog_question_changed' end
        local after=fingerprint(view)
        if expected_first~=nil and after==expected_first then return after,nil,question end
        unchanged=after==before and unchanged+1 or 0
        if unchanged>=2 then return after,nil,question end
    end
    return nil,'catalog_top_not_verified'
end
function M.capture(ctx,prefix,options)
    options=options or {}
    local save=options.save or function(label) return snapshot.capture(ctx,label,'evidence') end
    local valid=options.valid or function() return true end
    if pages.state()~='find' then return {status='paused',reason='catalog_find_not_open',pages=0} end
    if not valid() then return {status='paused',reason='catalog_question_changed',pages=0} end
    save(prefix .. 'p01')
    local captured=1
    for page=2,7 do
        -- Each saved page is the next swipe's before evidence.
        -- Keep multiple complete rows overlapping; a longer drag can skip faded rows.
        if not device.swipe(ctx,pages.features.find_title,prefix .. 'scroll_' .. page,{730,1350},{730,950},
            {capture_before=false,capture_after=false,settle_ms=350}) or pages.state()~='find' or not valid() then
            snapshot.capture(ctx,prefix .. 'incomplete')
            return {status='paused',reason='catalog_page_changed',pages=captured}
        end
        save(prefix .. string.format('p%02d',page))
        captured=page
    end
    return {status='paused',reason='find_catalog_observation_only',pages=captured}
end
function M.collect(ctx)
    local rounds=ctx.config.browse_rounds or 1
    if type(rounds)~='number' or rounds%1~=0 or rounds<1 or rounds>60 then
        return {status='blocked',reason='invalid_catalog_rounds'}
    end
    local cycles=ctx.config.browse_until_no_new_topics==true
    if cycles and rounds~=10 then return {status='blocked',reason='catalog_cycle_requires_ten_rounds'} end
    local limit=cycles and 60 or rounds
    local seen,new_topics,known_topics,incomplete_rounds={},0,0,0
    for round=1,limit do
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
        local name,category,reason=require('tasks.zhuagui.find').identify()
        if cycles and (reason or not name or category~='酒') then
            snapshot.capture(ctx,'catalog_topic_unverified')
            return {status='paused',reason='catalog_wine_topic_not_verified'}
        end
        local cycle=math.floor((round-1)/10)+1
        local prefix=string.format('catalog_r%03d_',round)
        log.write(ctx,'catalog_round','round=' .. round .. ' cycle=' .. cycle .. ' target=' .. tostring(name) ..
            ' category=' .. tostring(category) .. ' candidate_taps=0 new_accepts=0')
        local capture=M.capture(ctx,prefix)
        if capture.reason~='find_catalog_observation_only' and pages.state()~='retry' then
            return capture
        end
        if capture.pages<7 then incomplete_rounds=incomplete_rounds+1 end
        if name and not seen[name] then
            seen[name]=true;new_topics=new_topics+1;known_topics=known_topics+1
        end
        log.write(ctx,'catalog_round_done','round=' .. round .. ' pages=' .. capture.pages .. ' candidate_taps=0')
        if cycles and round%10==0 then
            log.write(ctx,'catalog_cycle_done','cycle=' .. cycle .. ' rounds=10 new_topics=' .. new_topics ..
                ' known_topics=' .. known_topics .. ' incomplete_rounds=' .. incomplete_rounds .. ' coverage_verified=false')
            if new_topics==0 then return {status='paused',reason='find_catalog_no_new_topics'} end
            new_topics=0;incomplete_rounds=0
        end
        if round<limit and not device.wait(function() return ({retry=true,dialogue=true,depart=true})[pages.state()] end,45,500) then
            snapshot.capture(ctx,prefix .. 'retry_missing')
            return {status='paused',reason='catalog_retry_not_observed'}
        end
    end
    if cycles then return {status='paused',reason='catalog_cycle_limit'} end
    return {status='paused',reason='find_catalog_observation_only'}
end
return M
