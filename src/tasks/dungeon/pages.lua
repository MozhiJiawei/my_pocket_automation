local detector = require('common.detector')
local M = {}
M.definitions = {wuji=require('tasks.dungeon.wuji.task'), chechi=require('tasks.dungeon.chechi.task')}
M.features = {
    list = require('tasks.dungeon.assets.list_title'),
    wuji = require('tasks.dungeon.wuji.assets.list_name'),
    enter = require('tasks.dungeon.assets.enter'),
    wuji_title = require('tasks.dungeon.wuji.assets.title'),
    start = require('tasks.dungeon.assets.start'),
    battle = require('common.assets.battle_title'),
    speed_one = require('tasks.dungeon.assets.speed_one'),
    loading = require('tasks.dungeon.assets.loading'),
    sealed_reward = require('tasks.dungeon.assets.sealed_reward'),
    wuji_completed = require('tasks.dungeon.wuji.assets.completed'),
    overview_back = require('tasks.dungeon.assets.overview_back'),
    list_back = require('tasks.dungeon.assets.list_back'),
    wuji_final_done = require('tasks.dungeon.wuji.assets.final_done'),
    chechi_card = require('tasks.dungeon.chechi.assets.card'),
    chechi = require('tasks.dungeon.chechi.assets.list_name'),
    switch_wuji_chechi = require('tasks.dungeon.assets.switch_wuji_chechi'),
    switch_chechi_wuji = require('tasks.dungeon.assets.switch_chechi_wuji'),
    chechi_title = require('tasks.dungeon.chechi.assets.title'),
    continue = require('tasks.dungeon.assets.continue'),
}
local function all_done(definition)
    if not definition.final_done then return false end
    for _, dy in ipairs({-550, -412, -275, -138, 0}) do
        local f = definition.final_done
        local copy = {}
        for k,v in pairs(f) do copy[k]=v end
        copy.region = {f.region[1], f.region[2]+dy, f.region[3], f.region[4]+dy}
        if not detector.present(copy) then return false end
    end
    return true
end
function M.state()
    if detector.present(M.features.switch_chechi_wuji) then return 'switch_chechi_wuji' end
    if detector.present(M.features.switch_wuji_chechi) then return 'switch_wuji_chechi' end
    if detector.present(M.features.sealed_reward) then
        for id,def in pairs(M.definitions) do
            if def.completed and detector.present(def.completed) then return id .. '_reward_sealed' end
        end
        return 'reward_unknown'
    end
    if detector.present(M.features.loading) then return 'loading' end
    if detector.present(M.features.battle) then return 'battle' end
    for id,def in pairs(M.definitions) do
        if detector.present(def.title) then
            if all_done(def) then return id .. '_done' end
            if detector.present(M.features.start) then return id .. '_ready' end
            return id .. '_active'
        end
    end
    if detector.present(M.features.list) then
        if detector.present(M.features.chechi) then return 'list_chechi' end
        return detector.present(M.features.wuji) and 'list_wuji' or 'list_other'
    end
    return 'unknown'
end
return M
