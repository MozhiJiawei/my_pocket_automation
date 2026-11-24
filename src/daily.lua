local navigation=require('common.navigation')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local dungeon_scope=require('tasks.dungeon.scope')
local M={}
local task_order={'shimen','zhuagui','dungeon','rewards'}
function M.run(ctx)
    local completed=0
    local selected=ctx.config.tasks
    assert(type(selected)=='table' and #selected>0,'selected tasks required')
    local wanted={}
    for _,name in ipairs(selected) do
        assert(not wanted[name],'duplicate selected task');wanted[name]=true
    end
    selected={}
    for _,name in ipairs(task_order) do
        if wanted[name] then selected[#selected+1]=name;wanted[name]=nil end
    end
    assert(next(wanted)==nil,'unsupported selected task')
    if not navigation.verify_roster(ctx) then
        snapshot.capture(ctx,'saved_roster_not_verified')
        log.write(ctx,'task_result','roster status=blocked reason=saved_roster_not_verified')
        log.write(ctx,'summary','all_roles_done=false selected_done=false daily_done=false reason=saved_roster_not_verified')
        return
    end
    local accounts=ctx.config.accounts
    local selection=ctx.config.selected_accounts or (ctx.config.selected_account and {ctx.config.selected_account})
    if selection then
        local wanted={}
        for _,alias in ipairs(selection) do
            assert(not wanted[alias],'duplicate selected role');wanted[alias]=true
        end
        accounts={}
        for _,account in ipairs(ctx.config.accounts) do
            if wanted[account.alias] then accounts[#accounts+1]=account end
        end
        assert(#accounts>0 and #accounts==#selection,'selected roles must be configured')
    end
    for _,account in ipairs(accounts) do
        ctx.account=account
        ctx.identity_verified=false
        ctx.dungeon_scope=nil
        log.write(ctx,'account',account.alias)
        local ready=navigation.prepare_recorded(ctx)
        if not ready then
            log.write(ctx,'task_result','account status=blocked reason=saved_role_not_ready')
            pcall(snapshot.capture,ctx,'role_identity_not_verified')
            log.write(ctx,'summary','all_roles_done=false selected_done=false daily_done=false reason=saved_role_not_ready')
            return
        else
            for _,name in ipairs(selected) do
                local cached=name=='dungeon' and dungeon_scope.completed(ctx) or require('completion').read(ctx,name)
                if name=='rewards' and cached and not dungeon_scope.rewards_scope_complete(ctx) then cached=nil end
                log.write(ctx,'task_start',name..' cached='..tostring(not not cached))
                local outcome=cached and {status='done',reason='daily_completion_ledger_verified'} or
                    require('tasks.'..name..'.task').run(ctx)
                log.write(ctx,'task_result',name..' status='..outcome.status..' reason='..(outcome.reason or ''))
                if outcome.status~='done' then
                    log.write(ctx,'error','task='..name..' status='..outcome.status..' reason='..(outcome.reason or ''))
                    if not outcome.failure_evidence then pcall(snapshot.capture,ctx,'task_'..name..'_incomplete') end
                    log.write(ctx,'summary','all_roles_done=false selected_done=false daily_done=false reason='..name..'_'..outcome.status)
                    return
                end
                if not navigation.finish_account(ctx) then
                    log.write(ctx,'task_result','navigation status=blocked reason=return_home_not_verified')
                    log.write(ctx,'error','task=navigation reason=return_home_not_verified')
                    pcall(snapshot.capture,ctx,'return_home_not_verified')
                    log.write(ctx,'summary','all_roles_done=false selected_done=false daily_done=false reason=return_home_not_verified')
                    return
                end
                log.write(ctx,'home_verified','account='..account.alias..' task='..name)
                if name=='dungeon' and not cached then dungeon_scope.mark_complete(ctx) end
            end
        end
        -- Every selected task and its return home were verified above.
        completed=completed+1
        log.write(ctx,'account_result','status=done')
    end
    local full={}
    for _,name in ipairs(selected) do full[name]=true end
    local done=completed==#accounts
    local all=done and not selection
    local daily=all and full.shimen and full.zhuagui and full.dungeon and full.rewards or false
    log.write(ctx,'summary','scope='..(selection and 'selected_roles' or 'roles')..' roles_expected='..#accounts..' roles_completed='..completed..
        ' all_roles_done='..tostring(all)..' selected_done='..tostring(done)..' daily_done='..tostring(daily))
end
return M
