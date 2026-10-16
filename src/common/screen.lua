-- getScreenSize returns the Android initial orientation, not init's coordinate space.
-- https://helpdoc.touchsprite.com/dev_docs/3.html
local M = {}
local direction = 0
local capture_reset=false
function M.init(value, refresh)
    assert(value==0 or value==1 or value==2,'invalid screen direction')
    -- Android may retain the capture stride from the previous app orientation.
    -- https://helpdoc.touchsprite.com/dev_docs/18/26.html
    if (refresh or not capture_reset) and type(resetScreen)=='function' then resetScreen();capture_reset=true end
    init(value)
    direction=value
end
function M.size()
    local w,h=getScreenSize()
    if direction~=0 then return h,w end
    return w,h
end
return M
