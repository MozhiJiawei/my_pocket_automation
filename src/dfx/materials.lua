-- Diagnostic originals only; never read these files as gameplay state.
local snapshot=require('dfx.snapshot')
local log=require('dfx.log')
local profile=require('dfx.find_profile')
local M={}
local function save(ctx,material,label)
    local path=profile.call(ctx,'snapshot',#material.paths+1,snapshot.capture,ctx,label,'buffer')
    material.paths[#material.paths+1]=path
    return path
end
function M.keep(ctx,reason)
    local material=ctx.recognition_materials
    if not material then return end
    profile.stop(ctx)
    for index,path in ipairs(material.paths) do
        if path:match('_%d+_pending_') then material.paths[index]=snapshot.retain(ctx,path) end
    end
    log.write(ctx,'recognition_materials','task='..material.task..' kind='..material.kind..
        ' account='..material.account..' prefix='..material.prefix..' pages='..#material.paths..' from_first='..tostring(material.from_first)..
        ' captured='..tostring(material.captured)..' coverage_verified=false reason='..reason)
    profile.flush(ctx,material,reason)
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
    if kind=='puzzle' then
        save(ctx,material,material.prefix..'p01')
        material.from_first=true;material.captured=true
        return true
    end
    assert(kind=='find','invalid recognition material kind')
    profile.start(ctx)
    local catalog=require('tasks.zhuagui.catalog')
    local first,reason,question=profile.call(ctx,'top',0,catalog.to_top,ctx)
    if not first then profile.result(ctx,false,reason);M.keep(ctx,reason);return false,reason end
    material.from_first=true
    material.question=question
    return true
end
-- Called by the solver immediately before searching each current page.
function M.capture_find(ctx,page)
    local material=ctx.recognition_materials
    if not material then return true end
    assert(material.kind=='find' and page>=1 and page<=7,'invalid find material page')
    if material.account~=(ctx.account and ctx.account.alias or 'none') then
        profile.result(ctx,false,'catalog_page_changed')
        M.keep(ctx,'catalog_page_changed');return false,'catalog_page_changed'
    end
    if page<=#material.paths then return true end
    assert(page==#material.paths+1,'find material page skipped')
    local stable,reason=profile.call(ctx,'stable',page,require('tasks.zhuagui.catalog').wait_still,ctx,material.question)
    if not stable then profile.result(ctx,false,reason);M.keep(ctx,reason);return false,reason end
    save(ctx,material,material.prefix..string.format('p%02d',page))
    material.captured=page==7
    return true
end
-- An unknown topic still gets one read-only traversal, without a solving pass.
function M.collect_find(ctx)
    local material=ctx.recognition_materials
    if not material then return nil end
    assert(material.kind=='find' and #material.paths==0,'find collection already started')
    local catalog=require('tasks.zhuagui.catalog')
    local capture=catalog.capture(ctx,material.prefix,{save=function(label)
        return save(ctx,material,label)
    end,valid=function() return catalog.question_key()==material.question end})
    material.captured=capture.reason=='find_catalog_observation_only'
    return capture
end
return M
