local screen = require('common.screen')
local detector = require('common.detector')
local log = require('dfx.log')
local snapshot = require('dfx.snapshot')
local M = {}
local app = 'com.netease.mhxyhtb'
local pages = {
    {name='home',direction=0,feature=require('common.assets.home_dungeon')},
    {name='saved_roles',direction=0,feature=require('common.assets.saved_account_picker')},
    {name='pocket_confirm',direction=1,feature=require('common.assets.pocket_confirm')},
    {name='pocket_entry',direction=1,feature=require('common.assets.pocket_entry')},
}
local function process_state()
    local checked,running=pcall(appIsRunning,app)
    if checked and (running==0 or running==1) then return running end
end
local function entry()
    local direction
    for _,page in ipairs(pages) do
        if direction~=page.direction then
            screen.init(page.direction,true)
            direction=page.direction
        end
        if detector.present(page.feature) then return page.name end
    end
end
local function blocked(ctx,reason)
    pcall(snapshot.capture,ctx,reason)
    return {status='blocked',reason=reason}
end
-- Application startup only; no login, role selection or daily task interaction.
function M.start(ctx)
    local running=process_state()
    if running==nil then return blocked(ctx,'game_process_state_unknown') end
    local state=running==1 and entry() or nil
    if not state then
        if running==0 then
            log.write(ctx,'application_start','package='..app)
            runApp(app) -- One request; a lost/unknown return must not cause another launch.
        end
        local deadline=os.time()+120
        repeat
            mSleep(1000)
            running=process_state()
            if running==nil then return blocked(ctx,'game_process_state_unknown') end
            state=running==1 and entry() or nil
        until state or os.time()>=deadline
    end
    if not state then
        return blocked(ctx,'game_entry_not_verified')
    end
    snapshot.capture(ctx,'game_entry_'..state,'evidence')
    log.write(ctx,'application_ready','package='..app..' page='..state)
    return {status='done',reason='game_entry_verified'}
end
return M
