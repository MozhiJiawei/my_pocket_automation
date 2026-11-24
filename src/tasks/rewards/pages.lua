local detector=require('common.detector')
local device=require('common.device')
local home=require('common.assets.home_dungeon')
local ghost_gourd=require('tasks.rewards.assets.ghost_gourd')
local M={features={}}
for _,name in ipairs({'inventory','task_tab','task_tab_selected','dungeon_tab','dungeon_tab_selected',
    'special_tab','special_tab_selected','treasury_tab','detail_title','detail_back','open_one','discard','discard_confirm','bonus_receipt','empty','card_corner'}) do
    M.features[name]=require('tasks.rewards.assets.'..name)
end
M.features.bonus_receipt.variants={require('tasks.rewards.assets.fragment_notice')}
M.features.ghost_gourd_card=ghost_gourd.list
for _,category in ipairs({'task','dungeon','special'}) do
    M.features[category..'_tab'].variants={M.features[category..'_tab_selected']}
end
function M.state()
    if detector.present(M.features.bonus_receipt) then return 'bonus_receipt' end
    if M.features.discard_confirm and detector.present(M.features.discard_confirm) then return 'discard_confirm' end
    if detector.present(M.features.detail_title) then return 'detail' end
    if detector.present(M.features.inventory) then return 'inventory' end
    if detector.present(home) then return 'home' end
    return 'unknown'
end
function M.open_treasury(ctx)
    local bag={}
    for k,v in pairs(home) do bag[k]=v end
    bag.tap_offset={bag.tap_offset[1]+116,bag.tap_offset[2]+817}
    if not device.tap(ctx,bag,'rewards_open_inventory') or
        not device.wait(function() return M.state()=='inventory' end,20) then
        return false,'rewards_inventory_entry_not_verified'
    end
    if not detector.present(M.features.task_tab) then
        if not device.tap(ctx,M.features.treasury_tab,'rewards_open_treasury') or
            not device.wait(function()
                return M.state()=='inventory' and detector.present(M.features.task_tab)
            end,20) then return false,'rewards_treasury_not_verified' end
    end
    return true
end
function M.ghost_gourd_count()
    keepScreen(true)
    local ok,count=pcall(function()
        if M.state()~='detail' or not detector.present(ghost_gourd.detail) then return nil end
        local two=detector.present(ghost_gourd[2])
        local three=detector.present(ghost_gourd[3])
        if two~=three then return two and 2 or 3 end
        return nil
    end)
    keepScreen(false)
    if not ok then error(count,0) end
    return count
end
function M.close_receipt(ctx)
    if M.state()~='bonus_receipt' then return true end
    return device.tap(ctx,M.features.bonus_receipt,'rewards_close_bonus_receipt',function()
        return M.state()=='bonus_receipt'
    end) and device.wait(function()
        local state=M.state()
        return state=='detail' or state=='inventory'
    end,20)
end
function M.close_detail(ctx)
    if not M.close_receipt(ctx) then return false end
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
