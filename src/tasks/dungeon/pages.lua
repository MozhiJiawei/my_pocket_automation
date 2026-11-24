local detector = require('common.detector')
local M = {}
M.definitions = {
    wuji = require('tasks.dungeon.wuji.task'),
    chechi = require('tasks.dungeon.chechi.task'),
    heifeng = require('tasks.dungeon.heifeng.task'),
    shuilu = require('tasks.dungeon.shuilu.task'),
    pingding = require('tasks.dungeon.pingding.task'),
}
M.features = {
    list = require('tasks.dungeon.assets.list_title'),
    wuji = require('tasks.dungeon.wuji.assets.list_name'),
    enter = require('tasks.dungeon.assets.enter'),
    wuji_title = require('tasks.dungeon.wuji.assets.title'),
    start = require('tasks.dungeon.assets.start'),
    continue_battle = require('tasks.dungeon.assets.continue_battle'),
    claim_confirm_wuji = require('tasks.dungeon.assets.claim_confirm_wuji'),
    claim_confirm_chechi = require('tasks.dungeon.assets.claim_confirm_chechi'),
    claim_confirm_heifeng = require('tasks.dungeon.assets.claim_confirm_heifeng'),
    claim_confirm_shuilu = require('tasks.dungeon.assets.claim_confirm_shuilu'),
    claim_confirm_pingding = require('tasks.dungeon.assets.claim_confirm_pingding'),
    claim_confirm_cost = require('tasks.dungeon.assets.claim_confirm_cost'),
    claim_confirm_button = require('tasks.dungeon.assets.claim_confirm_button'),
    claim_cancel = require('tasks.dungeon.assets.claim_cancel'),
    claim_receipt_wuji = require('tasks.dungeon.assets.claim_receipt_wuji'),
    claim_receipt_chechi = require('tasks.dungeon.assets.claim_receipt_chechi'),
    claim_receipt_heifeng = require('tasks.dungeon.assets.claim_receipt_heifeng'),
    claim_receipt_shuilu = require('tasks.dungeon.assets.claim_receipt_shuilu'),
    claim_receipt_pingding = require('tasks.dungeon.assets.claim_receipt_pingding'),
    claim_receipt_close = require('tasks.dungeon.assets.claim_receipt_close'),
    battle = require('common.assets.battle_title'),
    speed_one = require('tasks.dungeon.assets.speed_one'),
    loading = require('tasks.dungeon.assets.loading'),
    sealed_reward = require('tasks.dungeon.assets.sealed_reward'),
    wuji_completed = require('tasks.dungeon.wuji.assets.completed'),
    overview_back = require('tasks.dungeon.assets.overview_back'),
    list_back = require('tasks.dungeon.assets.list_back'),
    list_ended = require('tasks.dungeon.assets.list_ended'),
    wuji_final_done = require('tasks.dungeon.wuji.assets.final_done'),
    chechi_card = require('tasks.dungeon.chechi.assets.card'),
    chechi = require('tasks.dungeon.chechi.assets.list_name'),
    switch_wuji_chechi = require('tasks.dungeon.assets.switch_wuji_chechi'),
    switch_chechi_wuji = require('tasks.dungeon.assets.switch_chechi_wuji'),
    switch_message = require('tasks.dungeon.assets.switch_message'),
    switch_confirm = require('tasks.dungeon.assets.switch_confirm'),
    switch_cancel = require('tasks.dungeon.assets.switch_cancel'),
    chechi_title = require('tasks.dungeon.chechi.assets.title'),
    continue = require('tasks.dungeon.assets.continue'),
}
M.features.claim_confirm_button.variants = {require('tasks.dungeon.assets.claim_confirm_button_current')}
M.features.claim_cancel.variants = {require('tasks.dungeon.assets.claim_cancel_current')}
local switch_names = {
    wuji = require('tasks.dungeon.assets.switch_name_wuji'),
    chechi = require('tasks.dungeon.assets.switch_name_chechi'),
    heifeng = require('tasks.dungeon.assets.switch_name_heifeng'),
    shuilu = require('tasks.dungeon.assets.switch_name_shuilu'),
    pingding = require('tasks.dungeon.assets.switch_name_pingding'),
}
local function switch_name(previous_dungeon)
    local matched
    for id, name in pairs(switch_names) do
        local feature = name
        if previous_dungeon then
            -- The prior name is one line lower. Wrapping can shift its starting column left.
            feature = {}
            for key, value in pairs(name) do feature[key] = value end
            local region = name.region
            feature.region = {region[1]-43, region[2]+50, region[3], region[4]+50}
        end
        if detector.present(feature) then
            if matched then return nil end
            matched = id
        end
    end
    return matched
end
local function all_done(definition)
    -- The five-row overview uses the same completion glyph and row positions.
    local f = definition.final_done or M.features.wuji_final_done
    for _, dy in ipairs({-550, -412, -275, -138, 0}) do
        local copy = {}
        for k,v in pairs(f) do copy[k]=v end
        copy.region = {f.region[1], f.region[2]+dy, f.region[3], f.region[4]+dy}
        if not detector.present(copy) then return false end
    end
    return true
end
function M.switch_feature(state)
    local prior, target = state:match('^switch_(%w+)_(%w+)$')
    if M.definitions[prior] and M.definitions[target] and prior ~= target then
        return M.features[state] or M.features.switch_confirm
    end
end
function M.reward_claimed(id)
    local def=assert(M.definitions[id])
    if not detector.present(M.features.list) then return false end
    if def.claimed_card and detector.present(def.claimed_card) then return true end
    if def.ended_after_claim and detector.present(def.list_name) and detector.present(M.features.list_ended) then return true end
    return def.treasure_entry and detector.present(def.list_name) and detector.present(def.treasure_entry) or false
end
function M.state()
    if detector.present(M.features.claim_confirm_cost) then
        local matched
        for id in pairs(M.definitions) do
            local name = M.features['claim_confirm_' .. id]
            if name and detector.present(name) then
                if matched then return 'reward_unknown' end
                matched = id
            end
        end
        return matched and matched .. '_claim_confirm' or 'reward_unknown'
    end
    for id in pairs(M.definitions) do
        local feature = M.features['claim_receipt_' .. id]
        if feature and detector.present(feature) then return id .. '_claim_receipt' end
    end
    if detector.present(M.features.switch_message) then
        local prior, target = switch_name(true), switch_name(false)
        if prior and target and prior ~= target then return 'switch_' .. prior .. '_' .. target end
        return 'unknown'
    end
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
        for id,def in pairs(M.definitions) do
            if detector.present(def.list_name) then return 'list_' .. id end
        end
        return 'list_other'
    end
    return 'unknown'
end
return M
