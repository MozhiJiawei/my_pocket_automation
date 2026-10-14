local detector=require('common.detector')
local device=require('common.device')
local M={features={}}
for _,name in ipairs({'inventory','task_tab','task_tab_selected','dungeon_tab','dungeon_tab_selected',
    'special_tab','special_tab_selected','treasury_tab','detail_title','detail_back','open_one','discard','discard_confirm','empty','card_corner'}) do
    M.features[name]=require('tasks.rewards.assets.'..name)
end
for _,category in ipairs({'task','dungeon','special'}) do
    M.features[category..'_tab'].variants={M.features[category..'_tab_selected']}
end
function M.state()
    if M.features.discard_confirm and detector.present(M.features.discard_confirm) then return 'discard_confirm' end
    if detector.present(M.features.detail_title) then return 'detail' end
    if detector.present(M.features.inventory) then return 'inventory' end
    if detector.present(require('common.assets.home_dungeon')) then return 'home' end
    return 'unknown'
end
function M.close_detail(ctx)
    if M.state()~='detail' then return M.state()=='inventory' end
    return device.tap(ctx,M.features.detail_back,'rewards_close_detail') and
        device.wait(function() return M.state()=='inventory' end,20)
end
function M.select_category(ctx,category)
    if not ({task=true,dungeon=true,special=true})[category] or not M.close_detail(ctx) then return false end
    return device.tap(ctx,M.features[category..'_tab'],'rewards_'..category..'_tab') and
        device.wait(function() return M.state()=='inventory' and detector.present(M.features[category..'_tab_selected']) end,20)
end
function M.empty_category()
    return M.state()=='inventory' and detector.present(M.features.empty)
end
function M.cards()
    if M.state()~='inventory' then return nil end
    local cards={};local minimum=410
    for _=1,4 do
        if minimum>1270 then break end
        local feature={}
        for k,v in pairs(M.features.card_corner) do feature[k]=v end
        feature.region={800,minimum,870,1270}
        local found=detector.find(feature)
        if not found then break end
        local target_y=found.y+feature.tap_offset[2]
        if target_y>=450 and target_y<=1190 then
            feature.region={found.x-2,found.y-2,found.x+2,found.y+2}
            cards[#cards+1]=feature
        end
        minimum=found.y+200
    end
    return cards
end
return M
