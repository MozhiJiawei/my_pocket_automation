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
M.features.completion_dialogue=require('tasks.shimen.assets.completion_dialogue')
M.features.accept=require('tasks.shimen.assets.accept')
M.features.back=require('tasks.shimen.assets.back')
M.features.home=require('common.assets.home_dungeon')
M.features.task_list=require('tasks.zhuagui.assets.task_list_title')
M.features.task_card=require('tasks.shimen.assets.task_card')
M.features.completed_card=require('tasks.shimen.assets.completed_card')
M.features.prepare_puzzle=require('tasks.shimen.assets.prepare_puzzle')
M.features.catch=require('tasks.shimen.assets.catch')
M.features.intimidate=require('tasks.shimen.assets.intimidate')
M.features.duel=require('tasks.shimen.assets.duel')
M.features.choose_city=require('tasks.shimen.assets.choose_city')
M.features.choose_city.variants={require('tasks.shimen.assets.choose_jianye'),
    require('tasks.shimen.assets.choose_zhuzi'),require('tasks.shimen.assets.choose_xiliang')}
M.features.prepare_find=require('tasks.shimen.assets.prepare_find')
M.features.retry=require('tasks.shimen.assets.find_retry')
M.features.gourd_notice=require('tasks.shimen.assets.gourd_notice')
M.features.puzzle_retry_prompt=require('tasks.shimen.assets.puzzle_retry_prompt')
M.features.loading=require('tasks.shimen.assets.battle_loading')
M.features.loading.variants={require('tasks.dungeon.assets.loading')}
M.actions={go=M.features.go,catch=M.features.catch,intimidate=M.features.intimidate,
    duel=M.features.duel,choose_city=M.features.choose_city,
    deliver=M.features.deliver,dialogue=M.features.dialogue_next,
    prepare_find=M.features.prepare_find,retry=M.features.retry,
    completion_dialogue=M.features.dialogue_next,
    delivery_dialogue=M.features.dialogue_next,
    puzzle_retry=M.features.prepare_puzzle,prepare_puzzle=M.features.prepare_puzzle}
function M.count() return require('tasks.zhuagui.counter').read({750,208,805,229}) end
function M.state()
    if detector.present(M.features.gourd_notice) then return 'gourd_notice' end
    if detector.present(M.features.loading) then return 'loading' end
    if detector.present(M.features.puzzle) then return 'puzzle' end
    if detector.present(M.features.find) then return 'find' end
    if detector.present(M.features.battle) then return 'battle' end
    if detector.present(M.features.title) and detector.present(M.features.retry) then return 'retry' end
    if detector.present(M.features.title) and detector.present(M.features.completion_dialogue) and detector.present(M.features.dialogue_next) then return 'completion_dialogue' end
    if detector.present(M.features.title) and detector.present(M.features.idle) and detector.present(M.features.accept) then return 'ready' end
    if detector.present(M.features.title) and detector.present(M.features.idle) and detector.present(M.features.dialogue_next) then return 'delivery_dialogue' end
    if detector.present(M.features.title) and detector.present(M.features.dialogue_next) then return 'dialogue' end
    if detector.present(M.features.title) and detector.present(M.features.go) then return 'go' end
    if detector.present(M.features.title) and detector.present(M.features.choose_city) then return 'choose_city' end
    if detector.present(M.features.title) and detector.present(M.features.catch) then return 'catch' end
    if detector.present(M.features.title) and detector.present(M.features.intimidate) then return 'intimidate' end
    if detector.present(M.features.title) and detector.present(M.features.duel) then return 'duel' end
    if detector.present(M.features.title) and detector.present(M.features.prepare_find) then return 'prepare_find' end
    if detector.present(M.features.title) and detector.present(M.features.prepare_puzzle) then
        if detector.present(M.features.puzzle_retry_prompt) then return 'puzzle_retry' end
        return 'prepare_puzzle'
    end
    if detector.present(M.features.title) and detector.present(M.features.deliver) then return 'deliver' end
    if detector.present(M.features.home) then return 'home' end
    if detector.present(M.features.task_list) then
        if detector.present(M.features.completed_card) then return 'completed_card' end
        return 'task_list'
    end
    return 'unknown'
end
return M
