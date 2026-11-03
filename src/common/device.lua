local log = require('dfx.log')
local detector = require('common.detector')
local snapshot = require('dfx.snapshot')
local M = {}
function M.tap(ctx, feature, label, guard)
    if guard and not guard() then return false end
    local found = detector.find(feature)
    if not found then return false end
    snapshot.capture(ctx, label .. '_before', 'debug')
    found = detector.find(feature)
    if not found then
        log.write(ctx,'tap_skipped',label .. ' target_changed_during_capture')
        return false
    end
    if guard and not guard() then
        log.write(ctx,'tap_skipped',label .. ' precondition_changed_during_capture')
        return false
    end
    local offset=found.tap_offset or feature.tap_offset
    local x, y = found.x + offset[1], found.y + offset[2]
    local material=ctx.recognition_materials
    local trace=material and material.find_profile
    if trace and not trace.ended and trace.phase=='tap' then
        require('dfx.find_profile').target(ctx,trace.page,x,y)
    end
    log.write(ctx, 'tap', string.format('%s x=%d y=%d', label, x, y))
    -- Use the same primary contact as swipes, instead of TSLib's random index.
    tap(x, y, {ms=50,index=1})
    mSleep(1200)
    snapshot.capture(ctx, label .. '_after', 'debug')
    return true
end
function M.wait(predicate, attempts, interval)
    for _ = 1, attempts do
        if predicate() then return true end
        mSleep(interval or 500)
    end
    return false
end
function M.swipe(ctx, feature, label, from, to, options)
    options=options or {}
    if not detector.present(feature) then return false end
    if options.capture_before~=false then snapshot.capture(ctx, label .. '_before', 'debug') end
    log.write(ctx, 'swipe', label)
    if not detector.present(feature) then
        log.write(ctx,'swipe_skipped',label .. ' target_changed_during_capture')
        return false
    end
    touchDown(1, from[1], from[2])
    for i = 1, 20 do
        touchMove(1, math.floor(from[1] + (to[1]-from[1])*i/20), math.floor(from[2] + (to[2]-from[2])*i/20))
        mSleep(25)
    end
    touchUp(1, to[1], to[2])
    mSleep(options.settle_ms or 1200)
    if options.capture_after~=false then snapshot.capture(ctx, label .. '_after', 'debug') end
    return true
end
return M
