local data=require('tasks.zhuagui.assets.legacy')
local detector=require('common.detector')
local screen=require('common.screen')
local M={data=data}
local function round(value) return math.floor(value+0.5) end
function M.feature(source,scale,region,recolor)
    local w,h=screen.size()
    local function color(c)
        if not recolor then return c end
        -- Old blue hint glyphs to the measured new hint foreground palette.
        local r,g,b=math.floor(c/65536)%256,math.floor(c/256)%256,c%256
        return math.min(255,r+50)*65536+math.min(255,g+26)*256+math.min(255,b+19)
    end
    local points={}
    local minx,maxx,miny,maxy=0,0,0,0
    for x,y,c in source[2]:gmatch('(-?%d+)|(-?%d+)|(0x%x+)') do
        local dx,dy=round(tonumber(x)*scale),round(tonumber(y)*scale)
        minx,maxx=math.min(minx,dx),math.max(maxx,dx)
        miny,maxy=math.min(miny,dy),math.max(maxy,dy)
        points[#points+1]=string.format('%d|%d|0x%06x',dx,dy,color(tonumber(c)))
    end
    return {width=w,height=h,base=color(source[1]),offsets=table.concat(points,','),
        degree=source[3],region=region,tap_offset={round((minx+maxx)/2),round((miny+maxy)/2)}}
end
function M.target()
    local w,h=screen.size()
    if w~=900 or h~=1600 then return nil end
    local matched
    for name,source in pairs(data.targets) do
        -- Numeric key 1 is an unnamed old fallback, not an identified category.
        if type(name)=='string' then
            local found=false
            for _,scale in ipairs({1.65,w/data.width,h/data.height}) do
                for _,recolor in ipairs({false,true}) do
                    if detector.present(M.feature(source,scale,{65,350,830,415},recolor)) then found=true end
                end
            end
            if found then
                if matched and matched~=name then return nil,'legacy_target_ambiguous' end
                matched=name
            end
        end
    end
    return matched
end
function M.items(name)
    local w,h=screen.size()
    if w~=900 or h~=1600 then return {} end
    local features={}
    for _,scale in ipairs({w/data.width,h/data.height,1.75}) do
        for index,source in ipairs(data.items[name] or {}) do
            local feature=M.feature(source,scale,{65,540,825,1405})
            feature.legacy_index=index
            feature.legacy_scale=scale
            features[#features+1]=feature
        end
    end
    return features
end
return M
