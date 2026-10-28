-- One bounded, in-memory trace per live question. Format only retained failures.
local M={}
local phases={'top','identify','stable','snapshot','scan','scroll','guard','tap','verify'}
local function trace(ctx)
    local material=ctx.recognition_materials
    local current=material and material.find_profile
    if current and not current.ended then return current end
end
function M.start(ctx)
    if not ctx.profile then return end
    ctx.recognition_materials.find_profile={clock=ctx.profile.clock,
        started=ctx.profile.clock(),rows={},phase='top',page=0}
end
function M.row(ctx,page)
    local t=trace(ctx)
    if not t then return nil end
    assert(page>=0 and page<=7,'invalid find profile page')
    local row=t.rows[page]
    if not row then row={};t.rows[page]=row end
    return row
end
function M.set(ctx,page,values)
    local row=M.row(ctx,page)
    if row then for key,value in pairs(values) do row[key]=value end end
end
function M.target(ctx,page,x,y)
    local row=M.row(ctx,page)
    if not row then return end
    row.targets=row.targets or {}
    if #row.targets<10 then row.targets[#row.targets+1]={x,y} end
end
function M.call(ctx,phase,page,fn,...)
    local t=trace(ctx)
    if not t then return fn(...) end
    local row=M.row(ctx,page)
    t.phase,t.page=phase,page
    local started,cpu=t.clock(),os.clock()
    local values=table.pack(pcall(fn,...))
    local ended=t.clock()
    local sample=row[phase]
    if not sample then sample={at_ms=started-t.started,wall_ms=0,cpu_ms=0,calls=0};row[phase]=sample end
    sample.wall_ms=sample.wall_ms+math.max(0,ended-started)
    sample.cpu_ms=sample.cpu_ms+(os.clock()-cpu)*1000
    sample.calls=sample.calls+1
    if not values[1] then row.error=phase;error(values[2],0) end
    return table.unpack(values,2,values.n)
end
function M.result(ctx,ok,reason)
    local t=trace(ctx)
    if not t then return end
    t.solved,t.result,t.ended=ok,reason,t.clock()
end
function M.stop(ctx)
    local t=trace(ctx)
    if t and not t.ended then t.ended=t.clock() end
end
local function atom(value)
    return tostring(value):gsub('[%s=]','_')
end
function M.flush(ctx,material,reason)
    local t=material.find_profile
    if not t then return end
    material.find_profile=nil -- Repeated outer failure handling cannot print twice.
    if t.solved and (reason=='delivery_not_verified' or reason=='previous_result_not_verified') then return end
    local lines={}
    local measured=0
    for page=0,7 do
        local row=t.rows[page]
        if row then
            local fields={'scope=find_page','prefix='..material.prefix,'page='..page}
            if material.paths[page] then fields[#fields+1]='image='..material.paths[page]:match('[^/]+$') end
            for _,key in ipairs({'topic','required','features','candidates','searches','matches','selected','state','question_matches','error'}) do
                if row[key]~=nil then fields[#fields+1]=key..'='..atom(row[key]) end
            end
            if row.targets then
                local points={}
                for _,point in ipairs(row.targets) do points[#points+1]=point[1]..','..point[2] end
                fields[#fields+1]='targets='..table.concat(points,';')
            end
            for _,phase in ipairs(phases) do
                local s=row[phase]
                if s then
                    measured=measured+s.wall_ms
                    -- at,wall,cpu,calls: fixed order, milliseconds, no per-candidate timings.
                    fields[#fields+1]=string.format('%s=%.0f,%.0f,%.3f,%d',phase,s.at_ms,s.wall_ms,s.cpu_ms,s.calls)
                end
            end
            lines[#lines+1]=table.concat(fields,' ')
        end
    end
    local total=math.max(0,(t.ended or t.clock())-t.started)
    local log=require('dfx.log')
    log.write(ctx,'profile',string.format('scope=find_failure task=%s account=%s prefix=%s reason=%s solver_result=%s page=%d phase=%s pages=%d captured=%s wall_ms=%.0f other_ms=%.0f timing=at_wall_cpu_calls',
        material.task,material.account,material.prefix,atom(reason),atom(t.result or 'interrupted'),
        t.page,t.phase,#material.paths,tostring(material.captured),total,math.max(0,total-measured)))
    for _,line in ipairs(lines) do log.write(ctx,'profile',line) end
end
return M
