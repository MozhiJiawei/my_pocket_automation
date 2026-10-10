-- getScreenSize returns the Android initial orientation, not init's coordinate space.
-- https://helpdoc.touchsprite.com/dev_docs/3.html
local M = {}
local direction = 0
function M.init(value)
    assert(value==0 or value==1 or value==2,'invalid screen direction')
    init(value)
    direction=value
end
function M.size()
    local w,h=getScreenSize()
    if direction~=0 then return h,w end
    return w,h
end
return M
