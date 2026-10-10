local detector=require('common.detector')
local device=require('common.device')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local legacy=require('tasks.zhuagui.legacy')
local M={}
function M.identify()
    if not detector.present(require('tasks.zhuagui.assets.find_title')) then return nil,nil,'not_find_page' end
    for _,entry in ipairs({{'dew_wine','dew_wine','酒'},{'tiger_wine','tiger_wine','酒'},
        {'plum_wine','plum_wine','酒'},{'gold','legacy','黄金'},{'painting','legacy','书画'}}) do
        if detector.present(require('tasks.zhuagui.assets.target_' .. entry[1])) then return entry[2],entry[3] end
    end
    if detector.present(require('tasks.zhuagui.assets.target_weapon')) then return 'weapon','兵器' end
    if detector.present(require('tasks.zhuagui.assets.target_book')) then return 'legacy','书籍' end
    for _,id in ipairs({'wild','horse','zombie','skeleton','snake_wine'}) do
        if detector.present(require('tasks.zhuagui.assets.target_' .. id)) then
            return id,({wild='野鬼',horse='马面',zombie='僵尸',skeleton='骷髅怪',snake_wine='酒'})[id]
        end
    end
    if detector.present(require('tasks.zhuagui.assets.target_wine')) then return 'wine','酒' end
    local category,reason=legacy.target()
    if category then return 'legacy',category end
    return nil,nil,reason
end
function M.solve(ctx)
    local name,category,reason=M.identify()
    if reason then return false,reason end
    if not name then return false,'find_target_unknown' end
    if name=='weapon' then return false,'weapon_icon_requires_calibration' end
    if category=='酒' and name~='snake_wine' then return false,'wine_requires_specific_calibration' end
    log.write(ctx,'find_category','name=' .. category .. ' strategy=modern_then_scaled_legacy')
    local sources,features={},{}
    if name~='wine' and name~='legacy' then
        sources={(require('tasks.zhuagui.assets.icon_' .. name))}
        if name=='wild' or name=='zombie' then sources[#sources+1]=require('tasks.zhuagui.assets.icon_' .. name .. '_reverse') end
    end
    for _,source in ipairs(sources) do
    for turn=0,3 do
        local function rotate(x,y)
            for _=1,turn do x,y=-y,x end
            return x,y
        end
        local points={}
        for x,y,color in source.offsets:gmatch('(-?%d+)|(-?%d+)|(0x%x+)') do
            local rx,ry=rotate(tonumber(x),tonumber(y))
            points[#points+1]=rx .. '|' .. ry .. '|' .. color
        end
        local tx,ty=rotate(source.tap_offset[1],source.tap_offset[2])
        local feature={width=900,height=1600,base=source.base,offsets=table.concat(points,','),degree=90,
            region={65,540,825,1405},tap_offset={tx,ty}}
        feature.rotation=turn
        features[#features+1]=feature
    end
    end
    for _,feature in ipairs(legacy.items(category)) do features[#features+1]=feature end
    log.write(ctx,'find_search','features=' .. #features .. ' category=' .. category)
    for pass=1,6 do
    snapshot.capture(ctx,'find_catalog_page_' .. pass)
    for _,feature in ipairs(features) do
        if not detector.present(require('tasks.zhuagui.assets.find_title')) then return false,'find_page_changed' end
        if detector.present(feature) then
            log.write(ctx,'find_target',name .. ' rotation=' .. tostring(feature.rotation) ..
                ' legacy_index=' .. tostring(feature.legacy_index) .. ' scale=' .. tostring(feature.legacy_scale))
            if not device.tap(ctx,feature,'zhuagui_find_' .. name) then return false,'find_target_changed' end
            if not device.wait(function() return not detector.present(require('tasks.zhuagui.assets.find_title')) end,10,300) then
                return false,'find_click_not_confirmed'
            end
            return true,'find_clicked'
        end
    end
        if pass<6 then
            if not device.swipe(ctx,require('tasks.zhuagui.assets.find_title'),'zhuagui_find_scroll',{730,1350},{730,750}) then
                return false,'find_page_changed'
            end
        end
    end
    return false,'find_icon_not_found'
end
return M
