-- The landscape login spinner is a rotating gray ring at screen center.
-- Sample its shape rather than the moving highlight or the scenery behind it.
local ring = {{14,0},{10,10},{0,14},{-10,10},{-14,0},{-10,-10},{0,-14},{10,-10}}

return function()
    keepScreen(true)
    local ok, visible = pcall(function()
        local matches = 0
        for _, point in ipairs(ring) do
            local dx, dy = point[1], point[2]
            local outer = getColor(800 + dx, 450 + dy)
            local inner = getColor(800 + dx / 2, 450 + dy / 2)
            local r, g, b = math.floor(outer / 65536), math.floor(outer / 256) % 256, outer % 256
            local gray = math.min(r, g, b)
            local inner_dark = math.min(math.floor(inner / 65536), math.floor(inner / 256) % 256, inner % 256)
            if gray >= inner_dark + 25 and math.max(r, g, b) - gray <= 48 then
                matches = matches + 1
            end
        end
        return matches >= 6
    end)
    keepScreen(false)
    if not ok then error(visible, 0) end
    return visible
end
