local all=require('tasks.rewards.assets.discard_confirm')
local single=require('tasks.rewards.assets.discard_single_confirm')
local function cancel(feature,dx)
    local copy={}
    for k,v in pairs(feature) do if k~='variants' then copy[k]=v end end
    copy.tap_offset={feature.tap_offset[1]+dx,feature.tap_offset[2]}
    return copy
end
local feature=cancel(all,-254)
feature.variants={cancel(single,-392)}
return feature
