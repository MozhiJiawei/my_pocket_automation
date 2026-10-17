-- Diagnostic originals only; never read these files as gameplay state.
local snapshot=require('dfx.snapshot')
local log=require('dfx.log')
local M={}
function M.keep(ctx,reason)
    local material=ctx.recognition_materials
    if not material then return end
    for index,path in ipairs(material.paths) do
        if path:match('_%d+_pending_') then material.paths[index]=snapshot.retain(ctx,path) end
    end
    log.write(ctx,'recognition_materials','task='..material.task..' kind='..material.kind..
        ' account='..material.account..' prefix='..material.prefix..' pages='..#material.paths..' from_first='..tostring(material.from_first)..
        ' captured='..tostring(material.captured)..' coverage_verified=false reason='..reason)
    ctx.recognition_materials=nil
end
function M.clear(ctx)
    local material=ctx.recognition_materials
    if not material then return end
    if material.account~=(ctx.account and ctx.account.alias or 'none') then
        M.keep(ctx,'role_changed_before_verification');return
    end
    for _,path in ipairs(material.paths) do assert(os.remove(path),'temporary evidence cleanup failed') end
    ctx.recognition_materials=nil
end
function M.prepare(ctx,task,kind)
    if ctx.recognition_materials then M.keep(ctx,'previous_result_not_verified') end
    ctx.material_sequence=(ctx.material_sequence or 0)+1
    local material={task=task,kind=kind,account=ctx.account and ctx.account.alias or 'none',
        paths={},from_first=false,captured=false,
        prefix=string.format('%s_%s_r%03d_',task,kind,ctx.material_sequence)}
    ctx.recognition_materials=material
    local function save(label)
        local path=snapshot.capture(ctx,label,'buffer')
        material.paths[#material.paths+1]=path
        return path
    end
    if kind=='puzzle' then
        save(material.prefix..'p01')
        material.from_first=true;material.captured=true
        return true
    end
    assert(kind=='find','invalid recognition material kind')
    local catalog=require('tasks.zhuagui.catalog')
    local first,reason,question=catalog.to_top(ctx)
    if not first then M.keep(ctx,reason);return false,reason end
    material.from_first=true
    local capture=catalog.capture(ctx,material.prefix,{save=save,valid=function()
        return catalog.question_key()==question
    end})
    material.captured=capture.reason=='find_catalog_observation_only'
    if not material.captured then M.keep(ctx,capture.reason);return false,capture.reason end
    local restored,restore_reason=catalog.to_top(ctx,question,first)
    if restored~=first then
        reason=restore_reason or 'catalog_first_frame_not_restored'
        M.keep(ctx,reason);return false,reason
    end
    return true
end
return M
