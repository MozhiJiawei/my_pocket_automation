local device=require('common.device')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local M={}
local DEFAULT_VIEW={50,310,850,1420}
-- A caller holding one observation frame owns its release, including on error.
local function fingerprint(view,held)
    if not held then keepScreen(true) end
    local ok,key=pcall(function()
        local hash=0
        for row=1,13 do
            for column=1,9 do
                local x=math.floor(view[1]+(view[3]-view[1])*(column-.5)/9)
                local y=math.floor(view[2]+(view[4]-view[2])*(row-.5)/13)
                local color=getColor(x,y)
                local r=math.floor(color/65536/16)
                local g=math.floor(color/256)%256
                local b=color%256
                hash=(hash*31+r*256+math.floor(g/16)*16+math.floor(b/16))%2147483647
            end
        end
        return hash
    end)
    if not held then keepScreen(false) end
    if not ok then error(key,0) end
    return key
end
M.fingerprint=fingerprint
local function stable(spec,view)
    local previous,count=nil,0
    for _=1,16 do
        if not spec.valid() then return nil,'list_changed' end
        local key=fingerprint(view)
        count=key==previous and count+1 or 1
        if count>=3 then return key end
        previous=key
        mSleep(150)
    end
    return nil,'list_not_stable'
end
local function gesture(view,axis,reverse,attempt)
    local from,to
    if axis=='horizontal' then
        local y=math.floor((view[2]+view[4])/2)
        local start=reverse and (.20+(attempt-1)*.18) or (.84-(attempt-1)*.18)
        local finish=reverse and math.min(.90,start+.64) or math.max(.10,start-.64)
        from={math.floor(view[1]+(view[3]-view[1])*start),y}
        to={math.floor(view[1]+(view[3]-view[1])*finish),y}
    else
        local x=math.floor(view[1]+(view[3]-view[1])*.91)
        local start=reverse and (.20+(attempt-1)*.15) or (.85-(attempt-1)*.15)
        local finish=reverse and math.min(.90,start+.55) or math.max(.10,start-.55)
        from={x,math.floor(view[2]+(view[4]-view[2])*start)}
        to={x,math.floor(view[2]+(view[4]-view[2])*finish)}
    end
    return from,to
end
-- inspect returns a business match, never an inferred completion or a count.
function M.find(ctx,spec)
    assert(type(spec.valid)=='function' and type(spec.inspect)=='function' and spec.page,'list specification required')
    local view=spec.view or DEFAULT_VIEW
    local limit=spec.max_forward or 8
    assert(limit>=1 and limit<=12,'bounded list traversal required')
    local function fail(reason)
        log.write(ctx,'list_scan_blocked','name='..spec.name..' reason='..reason)
        snapshot.capture(ctx,'list_'..spec.name..'_'..reason)
        return nil,reason
    end
    local function observe(direction,step)
        local key,reason=stable(spec,view)
        if not key then return nil,reason end
        if not spec.valid() then return nil,'list_changed' end
        local match=spec.inspect()
        log.write(ctx,'list_scan','name='..spec.name..' direction='..direction..' step='..step..' frame='..key..' found='..tostring(match~=nil))
        return match,nil,key
    end
    local match,reason,key=observe('current',0)
    if reason then return fail(reason) end
    if match then return match end
    for leg=1,2 do
        local direction=leg==1 and 'forward' or 'reverse'
        local seen={[key]=true}
        for step=1,limit*(leg==1 and 1 or 2) do
            local before,moved=key,false
            -- A drag can land in a non-scrollable gap. Only confirm an edge
            -- after distinct start points all leave the stable viewport unchanged.
            for attempt=1,3 do
                local from,to=gesture(view,spec.axis,leg==2,attempt)
                if not spec.valid() or not device.swipe(ctx,spec.page,'list_'..spec.name..'_'..direction,from,to,{settle_ms=350}) then
                    return fail('list_changed')
                end
                match,reason,key=observe(direction,step)
                if reason then return fail(reason) end
                if match then return match end
                if key~=before then moved=true;break end
                log.write(ctx,'list_drag_unchanged','name='..spec.name..' direction='..direction..' step='..step..' attempt='..attempt)
            end
            if not moved or seen[key] then
                log.write(ctx,'list_boundary','name='..spec.name..' direction='..direction..' repeated_frame=true')
                break
            end
            seen[key]=true
        end
    end
    return fail('target_not_found')
end
function M.activate(ctx,spec,match,label)
    if not match.feature then
        local current=spec.valid() and spec.inspect()
        return current and current.kind==match.kind or false
    end
    return device.tap(ctx,match.feature,label,function()
        if not spec.valid() then return false end
        local current=spec.inspect()
        return current and current.kind==match.kind and current.feature==match.feature
    end)
end
return M
