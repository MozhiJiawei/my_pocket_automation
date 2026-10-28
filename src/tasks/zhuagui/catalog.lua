-- Observation only: retry the existing puzzle, scroll, and save every page.
local pages=require('tasks.zhuagui.pages')
local device=require('common.device')
local snapshot=require('dfx.snapshot')
local log=require('dfx.log')
local M={}
local profile=require('dfx.find_profile')
-- Only page continuity uses this sample; answer recognition stays unchanged.
function M.question_key(held)
    if not held then keepScreen(true) end
    local ok,colors=pcall(function()
        local sample={}
        -- Exclude the countdown bar and selected-item counter.
        for row=1,13 do
            for column=1,9 do
                local x=math.floor(60+520*(column-.5)/9)
                local y=math.floor(335+85*(row-.5)/13)
                sample[#sample+1]=getColor(x,y)
            end
        end
        return sample
    end)
    if not held then keepScreen(false) end
    if not ok then error(colors,0) end
    return colors
end
function M.same_question(actual,expected)
    if #actual~=#expected then return false end
    for index,color in ipairs(actual) do
        local reference=expected[index]
        for _=1,3 do
            if math.abs(color%256-reference%256)>1 then return false end
            color=math.floor(color/256);reference=math.floor(reference/256)
        end
    end
    return true
end
local function frame_key(held)
    local fingerprint=require('common.list_navigation').fingerprint
    -- Item artwork rotates and the scroll thumb fades. Fixed cell borders stay
    -- unchanged; accept their row phase only after the upward boundary is proven.
    return fingerprint({62,535,66,1405},held)
end
local function verified_find(ctx,valid,with_frame)
    -- A live recognition read may straddle rendering frames. Reobserve without
    -- input before declaring a different page or question; never accept a new key.
    for attempt=1,3 do
        -- Observe state, question and row borders on the same native frame.
        -- Nested fingerprint reads must not release or recapture that frame.
        local held=valid or with_frame
        if held then keepScreen(true) end
        local observed=table.pack(pcall(function()
            local state=pages.state()
            local actual=held and state=='find' and M.question_key(true) or nil
            local matches=state=='find' and (not valid or valid(actual))
            local key=matches and with_frame and frame_key(true) or nil
            return state,matches,actual,key
        end))
        if held then keepScreen(false) end
        if not observed[1] then error(observed[2],0) end
        local state,matches,actual,key=table.unpack(observed,2,observed.n)
        local material=ctx.recognition_materials
        local trace=material and material.find_profile
        if trace then profile.set(ctx,trace.page,{state=state}) end
        if matches then return true,nil,actual,key end
        log.write(ctx,'catalog_guard','attempt='..attempt..' state='..state..' question_matches='..tostring(matches))
        if attempt<3 then mSleep(100) end
    end
    return false
end
local function question_guard(ctx,question)
    return function(actual)
        local matches=M.same_question(actual,question)
        local material=ctx.recognition_materials
        local trace=material and material.find_profile
        if trace then profile.set(ctx,trace.page,{question_matches=matches}) end
        return matches
    end
end
function M.verify_question(ctx,question)
    return verified_find(ctx,question_guard(ctx,question))
end
function M.wait_still(ctx,question)
    local previous,previous_question,count=nil,nil,0
    local valid=question and question_guard(ctx,question) or nil
    for _=1,16 do
        local verified,_,actual,key=verified_find(ctx,valid,true)
        if not verified then return false,'catalog_page_changed' end
        -- The scroll thumb fades even after motion stops; only fixed row borders
        -- establish stability. Keep the original question reference immutable.
        count=key==previous and M.same_question(actual,previous_question) and count+1 or 1
        if count>=3 then return true,nil,actual end
        previous,previous_question=key,actual
        mSleep(100)
    end
    return false,'catalog_scroll_not_stable'
end
function M.to_top(ctx,question,expected_first)
    if not question then
        local stable,reason,observed=M.wait_still(ctx)
        if not stable then return nil,reason end
        question=observed
    end
    local unchanged=0
    for attempt=1,12 do
        if not M.verify_question(ctx,question) then return nil,'catalog_question_changed' end
        local before=frame_key()
        local x=attempt%2==0 and 810 or 730
        if not device.swipe(ctx,pages.features.find_title,'catalog_to_top',{x,750},{x,1350},
            {capture_before=false,capture_after=ctx.config and ctx.config.routine_screenshots==true,
             settle_ms=350}) then return nil,'catalog_scroll_not_verified' end
        if not M.verify_question(ctx,question) then return nil,'catalog_question_changed' end
        local after=frame_key()
        log.write(ctx,'catalog_top','attempt='..attempt..' before='..before..' after='..after..' expected='..tostring(expected_first))
        unchanged=after==before and unchanged+1 or 0
        if unchanged>=2 then return after,nil,question end
    end
    return nil,'catalog_top_not_verified'
end
function M.capture(ctx,prefix,options)
    options=options or {}
    local save=options.save or function(label) return snapshot.capture(ctx,label,'evidence') end
    local valid=options.valid
    if not verified_find(ctx) then return {status='paused',reason='catalog_find_not_open',pages=0} end
    if valid and not valid() then return {status='paused',reason='catalog_question_changed',pages=0} end
    save(prefix .. 'p01')
    local captured=1
    for page=2,7 do
        -- Each saved page is the next swipe's before evidence.
        -- Keep multiple complete rows overlapping; a longer drag can skip faded rows.
        if not profile.call(ctx,'scroll',page-1,device.swipe,ctx,pages.features.find_title,prefix .. 'scroll_' .. page,{730,1350},{730,950},
            {capture_before=false,capture_after=false,settle_ms=350}) or not profile.call(ctx,'guard',page,verified_find,ctx,valid) then
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
