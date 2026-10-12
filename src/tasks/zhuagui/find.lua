local detector=require('common.detector')
local device=require('common.device')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local legacy=require('tasks.zhuagui.legacy')
local catalog=require('tasks.zhuagui.assets.catalog')
local title=require('tasks.zhuagui.assets.find_title')
local expired=require('tasks.zhuagui.assets.find_time_expired')
local M={}
local function scan(features)
    -- https://helpdoc.touchsprite.com/dev_docs/5.html
    -- One captured frame for the whole read-only search. Never act while held.
    keepScreen(true)
    local ok,feature,reason=pcall(function()
        if not detector.present(title) then return nil,'find_page_changed' end
        if detector.present(expired) then return nil,'find_time_expired' end
        for _,candidate in ipairs(features) do
            if detector.present(candidate) then return candidate end
        end
    end)
    keepScreen(false)
    if not ok then error(feature) end
    return feature,reason
end
function M.identify()
    if not detector.present(title) then return nil,nil,'not_find_page' end
    for _,entry in ipairs({{'dew_wine','dew_wine','酒'},{'tiger_wine','tiger_wine','酒'},
        {'plum_wine','plum_wine','酒'},{'gold','legacy','黄金'},{'painting','legacy','书画'}}) do
        if detector.present(require('tasks.zhuagui.assets.target_' .. entry[1])) then return entry[2],entry[3] end
    end
    if detector.present(require('tasks.zhuagui.assets.target_weapon')) then return 'weapon','兵器' end
    if detector.present(require('tasks.zhuagui.assets.target_book')) then return 'legacy','书籍' end
    for _,id in ipairs({'wild','horse','bull','paper','incense','candle','zombie','skeleton','snake_wine'}) do
        if detector.present(require('tasks.zhuagui.assets.target_' .. id)) then
            return id,({wild='野鬼',horse='马面',bull='牛头',paper='黄纸',incense='香炉',candle='蜡烛',zombie='僵尸',skeleton='骷髅怪',snake_wine='酒'})[id]
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
    if category=='酒' and name~='snake_wine' and name~='wine' then return false,'wine_requires_specific_calibration' end
    local features=catalog[name] or catalog[category] or legacy.items(category)
    log.write(ctx,'find_search','features=' .. #features .. ' category=' .. category)
    for pass=1,6 do
        snapshot.capture(ctx,'find_catalog_page_' .. pass, 'debug')
        local started=os.time()
        local feature,scan_reason=scan(features)
        log.write(ctx,'find_scan','page='..pass..' features='..#features..' seconds='..(os.time()-started)..
            ' matched='..tostring(feature~=nil))
        if scan_reason then return false,scan_reason,category end
        if feature then
            if not detector.present(title) then return false,'find_page_changed',category end
            if detector.present(expired) then return false,'find_time_expired',category end
            log.write(ctx,'find_target',name .. ' rotation=' .. tostring(feature.rotation) ..
                ' mirror='..tostring(feature.mirror)..' calibration=' .. tostring(feature.calibration_id))
            if not device.tap(ctx,feature,'zhuagui_find_' .. name) then return false,'find_target_changed',category end
            if not device.wait(function() return not detector.present(title) end,10,300) then
                return false,'find_click_not_confirmed',category
            end
            return true,'find_clicked'
        end
        if pass<6 and not device.swipe(ctx,title,'zhuagui_find_scroll',{730,1350},{730,750}) then
            return false,'find_page_changed',category
        end
    end
    return false,'find_icon_not_found',category
end
return M
