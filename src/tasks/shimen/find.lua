local detector=require('common.detector')
local matcher=require('common.find_items')
local resources=require('tasks.shimen.assets.catalog')
local questions=require('tasks.shimen.assets.questions')
local profile=require('dfx.find_profile')
local M={}
function M.identify()
    if not detector.present(questions.title) then return nil,'not_find_page' end
    for _,entry in ipairs(questions.topics) do
        for _,feature in ipairs(entry.features) do
            if detector.present(feature) then return entry.name end
        end
    end
    return nil,'find_target_unknown'
end
function M.read()
    local topic,reason=M.identify()
    if not topic then return nil,{},reason end
    local matches,scan_reason=matcher.scan(resources[topic](),questions.title,nil,true)
    return topic,matches or {},scan_reason
end
local function solve(ctx)
    local device=require('common.device')
    local expired=require('tasks.zhuagui.assets.find_time_expired')
    local required=ctx.config.shimen_needed or 2
    assert(required>=1 and required<=10 and required%1==0,'invalid item count')
    local selected={}
    local topic,reason=profile.call(ctx,'identify',0,M.identify)
    profile.set(ctx,0,{topic=topic or 'unknown',required=required})
    if not topic then
        local capture=require('dfx.materials').collect_find(ctx)
        if capture and capture.reason~='find_catalog_observation_only' then return false,capture.reason end
        return false,reason
    end
    local features=resources[topic]()
    profile.set(ctx,0,{features=#features})
    for page=1,7 do
        local captured,capture_reason=require('dfx.materials').capture_find(ctx,page)
        if not captured then return false,capture_reason end
        -- Find only as many answers as this attempt still needs. Full enumeration
        -- remains available through read() for offline scoring and annotation.
        local points,reason=profile.call(ctx,'scan',page,matcher.scan,features,questions.title,expired,true,
            required-#selected,profile.row(ctx,page))
        profile.set(ctx,page,{matches=points and #points or 0,selected=#selected})
        if reason then return false,reason end
        require('dfx.log').write(ctx,'shimen_find','page='..page..' matches='..#points..' selected='..#selected..' required='..required)
        if require('common.detector').present(expired) then return false,'find_time_expired' end
        for _,point in ipairs(points) do
            local duplicate=false
            for _,previous in ipairs(selected) do
                if previous.page==page and math.abs(previous.x-point.x)<50 and math.abs(previous.y-point.y)<50 then duplicate=true end
            end
            if not duplicate then
                if not detector.present(questions.title) then return false,'find_page_changed' end
                if detector.present(expired) then return false,'find_time_expired' end
                -- A small, nonempty search box tolerates final scroll settling;
                -- retain the full signature and never search another icon.
                local anchor=point.feature.region
                point.feature.region={anchor[1]-4,anchor[2]-4,anchor[3]+4,anchor[4]+4}
                require('dfx.log').write(ctx,'shimen_find_target','page='..page..' x='..point.x..' y='..point.y)
                if not profile.call(ctx,'tap',page,device.tap,ctx,point.feature,'shimen_find_item') then return false,'find_target_changed' end
                selected[#selected+1]={page=page,x=point.x,y=point.y}
                profile.set(ctx,page,{selected=#selected})
                if #selected<required then
                    if not detector.present(questions.title) then return false,'find_incomplete_exit' end
                elseif profile.call(ctx,'verify',page,device.wait,function() return not detector.present(questions.title) end,10,200) then
                    return true,'find_completed'
                end
                if #selected>=required then return false,'find_click_not_confirmed' end
            end
        end
        if page<7 and not profile.call(ctx,'scroll',page,device.swipe,ctx,questions.title,'shimen_find_scroll',{730,1350},{730,950},
            {settle_ms=350}) then
            return false,'find_page_changed'
        end
    end
    return false,'find_icon_not_found'
end
function M.solve(ctx)
    local ok,reason=solve(ctx)
    profile.result(ctx,ok,reason)
    return ok,reason
end
return M
