local detector = require('common.detector')
local M = {}
M.features = {
    puzzle=require('tasks.zhuagui.assets.puzzle'),
    quota_dialogue=require('tasks.zhuagui.assets.quota_dialogue'),
    gourd_prompt=require('tasks.zhuagui.assets.gourd_prompt'),
    retry=require('tasks.zhuagui.assets.retry'),
    battle=require('tasks.zhuagui.assets.battle'),
    depart=require('tasks.zhuagui.assets.depart'),
    find_title=require('tasks.zhuagui.assets.find_title'),
    target_wild=require('tasks.zhuagui.assets.target_wild'),
    dialogue_next=require('tasks.zhuagui.assets.dialogue_next'),
    go=require('tasks.zhuagui.assets.go'),
    cancel=require('tasks.zhuagui.assets.cancel'),
    rules=require('tasks.zhuagui.assets.rules'),
    title=require('tasks.zhuagui.assets.title'),
    idle=require('tasks.zhuagui.assets.idle'),
    cost_three=require('tasks.zhuagui.assets.cost_three'),
    accept=require('tasks.zhuagui.assets.accept'),
    home_tasks=require('tasks.zhuagui.assets.home_tasks'),
    task_card=require('tasks.zhuagui.assets.task_card'),
    task_list_title=require('tasks.zhuagui.assets.task_list_title'),
    completed_card=require('tasks.zhuagui.assets.completed_card'),
    task_tutorial=require('tasks.zhuagui.assets.task_tutorial'),
    calendar_tutorial=require('tasks.zhuagui.assets.calendar_tutorial'),
}
function M.state()
    if detector.present(M.features.gourd_prompt) then return 'unknown' end
    if detector.present(M.features.quota_dialogue) then return 'quota_dialogue' end
    if detector.present(M.features.battle) then return 'battle' end
    if detector.present(M.features.puzzle.title) then return 'puzzle' end
    if detector.present(M.features.find_title) then return 'find' end
    if detector.present(M.features.dialogue_next) then return 'dialogue' end
    if detector.present(M.features.rules) then return 'rules' end
    if detector.present(M.features.task_tutorial) then return 'task_tutorial' end
    if detector.present(M.features.calendar_tutorial) then return 'calendar_tutorial' end
    if detector.present(M.features.title) then
        if detector.present(M.features.puzzle.retry_prompt) and detector.present(M.features.puzzle.retry_button) then return 'puzzle_retry' end
        if detector.present(M.features.retry) then return 'retry' end
        if detector.present(M.features.idle) and not detector.present(M.features.accept)
            and require('tasks.zhuagui.counter').read()==25 then return 'quota_idle' end
        if detector.present(M.features.depart) then return 'depart' end
        if detector.present(M.features.go) then return 'go' end
        if detector.present(M.features.idle) and detector.present(M.features.cost_three) and detector.present(M.features.accept) then
            return 'ready_cost_three'
        end
        return 'active_uncalibrated'
    end
    if detector.present(M.features.task_list_title) then
        if detector.present(M.features.completed_card) then return 'quota_completed_card' end
        return 'task_list'
    end
    if detector.present(M.features.task_card) then return 'task_list' end
    return 'unknown'
end
return M
