local M = {}
function M.find(feature)
    local w, h = require('common.screen').size()
    if w ~= feature.width or h ~= feature.height then return nil end
    local x, y = findMultiColorInRegionFuzzy(feature.base, feature.offsets,
        feature.degree or 90, table.unpack(feature.region))
    if x == -1 then
        for _,variant in ipairs(feature.variants or {}) do
            local found=M.find(variant)
            if found then return found end
        end
        return nil
    end
    return {x = x, y = y, tap_offset=feature.tap_offset}
end
function M.present(feature) return M.find(feature) ~= nil end
return M
