local M={}
local detector=require('common.detector')
-- Known flow controls are calibrated from inspected captures; unknown pages stop.
M.features={find=require('tasks.shimen.assets.questions').title,
    puzzle=require('tasks.zhuagui.assets.puzzle').title,
    battle=require('tasks.zhuagui.assets.battle')}
M.features.title=require('tasks.shimen.assets.title')
M.features.go=require('tasks.shimen.assets.go')
M.features.deliver=require('tasks.shimen.assets.deliver')
M.features.idle=require('tasks.shimen.assets.idle')
M.features.dialogue_next=require('tasks.shimen.assets.dialogue_next')
M.features.accept=require('tasks.shimen.assets.accept')
M.features.back=require('tasks.shimen.assets.back')
M.features.home=require('common.assets.home_dungeon')
M.features.task_list=require('tasks.zhuagui.assets.task_list_title')
M.features.task_card=require('tasks.shimen.assets.task_card')
M.features.prepare_puzzle=require('tasks.shimen.assets.prepare_puzzle')
M.actions={go=M.features.go,deliver=M.features.deliver,dialogue=M.features.dialogue_next,prepare_puzzle=M.features.prepare_puzzle}
function M.count() return require('tasks.zhuagui.counter').read({750,208,805,229}) end
function M.state()
    if detector.present(M.features.puzzle) then return 'puzzle' end
    if detector.present(M.features.find) then return 'find' end
    if detector.present(M.features.battle) then return 'battle' end
    if detector.present(M.features.title) and detector.present(M.features.idle) and detector.present(M.features.accept) then return 'ready' end
    if detector.present(M.features.title) and detector.present(M.features.dialogue_next) then return 'dialogue' end
    if detector.present(M.features.title) and detector.present(M.features.go) then return 'go' end
    if detector.present(M.features.title) and detector.present(M.features.prepare_puzzle) then return 'prepare_puzzle' end
    if detector.present(M.features.title) and detector.present(M.features.deliver) then return 'deliver' end
    if detector.present(M.features.home) then return 'home' end
    if detector.present(M.features.task_list) and detector.present(M.features.task_card) then return 'task_list' end
    return 'unknown'
end
return M
