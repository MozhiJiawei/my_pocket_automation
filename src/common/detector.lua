local M = {}
function M.find(feature)
    local w, h = require('common.screen').size()
    if w ~= feature.width or h ~= feature.height then return nil end
    local x, y = findMultiColorInRegionFuzzy(feature.base, feature.offsets,
        feature.degree or 90, table.unpack(feature.region))
    if x == -1 then return nil end
    return {x = x, y = y}
end
function M.present(feature) return M.find(feature) ~= nil end
return M
