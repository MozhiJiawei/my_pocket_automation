-- Shared read-only color search. Directions are compiled offline.
local detector=require('common.detector')
local M={}
function M.scan(features,title,expired,all,limit)
    keepScreen(true)
    local ok,result,reason=pcall(function()
        if not detector.present(title) then return nil,'find_page_changed' end
        if expired and detector.present(expired) then return nil,'find_time_expired' end
        local matches={}
        for _,candidate in ipairs(features) do
            if not all then
                if detector.present(candidate) then return candidate end
            else
                local regions={candidate.region}
                while #regions>0 do
                    local region=table.remove(regions)
                    local feature={width=candidate.width,height=candidate.height,base=candidate.base,
                        offsets=candidate.offsets,degree=candidate.degree,region=region,tap_offset=candidate.tap_offset}
                    local found=detector.find(feature)
                    if found then
                        local x=found.x+candidate.tap_offset[1]
                        local y=found.y+candidate.tap_offset[2]
                        local duplicate=false
                        for _,p in ipairs(matches) do
                            if math.abs(p.x-x)<50 and math.abs(p.y-y)<50 then duplicate=true;break end
                        end
                        if not duplicate then
                            -- Keep the exact matching anchor for guarded device clicks.
                            feature.region={found.x,found.y,found.x,found.y}
                            -- Artwork can rotate after releasing the held scan.
                            -- Revalidate compiled orientations of this signature
                            -- within the same target center, never another cell.
                            feature.variants={}
                            for _,variant in ipairs(features) do
                                if variant.base==candidate.base then
                                    local offset=variant.tap_offset
                                    feature.variants[#feature.variants+1]={width=variant.width,height=variant.height,
                                        base=variant.base,offsets=variant.offsets,degree=variant.degree,
                                        tap_offset=offset,region={x-offset[1]-4,y-offset[2]-4,x-offset[1]+4,y-offset[2]+4}}
                                end
                            end
                            matches[#matches+1]={x=x,y=y,feature=feature}
                            if #matches>=(limit or 30) then return matches end
                        end
                        -- Exclude this complete icon, then search the remaining rectangles.
                        local left,right,top,bottom=x-65,x+65,y-65,y+65
                        local function add(a,b,c,d)
                            if a<=c and b<=d then regions[#regions+1]={a,b,c,d} end
                        end
                        add(region[1],region[2],region[3],math.min(region[4],top-1))
                        add(region[1],math.max(region[2],bottom+1),region[3],region[4])
                        add(region[1],math.max(region[2],top),math.min(region[3],left-1),math.min(region[4],bottom))
                        add(math.max(region[1],right+1),math.max(region[2],top),region[3],math.min(region[4],bottom))
                    end
                end
            end
        end
        return all and matches or nil
    end)
    keepScreen(false)
    if not ok then error(result) end
    return result,reason
end
return M
