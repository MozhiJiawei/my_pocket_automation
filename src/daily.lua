local navigation=require('common.navigation')
local log=require('dfx.log')
local snapshot=require('dfx.snapshot')
local M={}
function M.run(ctx)
    local completed,failed=0,0
    local selected=ctx.config.tasks
    assert(type(selected)=='table' and #selected>0,'selected tasks required')
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
        log.write(ctx,'account',account.alias)
        local ready=navigation.prepare_recorded(ctx)
        local complete=ready
        if not ready then
            snapshot.capture(ctx,'role_identity_not_verified')
            log.write(ctx,'task_result','account status=blocked reason=saved_role_not_ready')
        else
            for _,name in ipairs(selected) do
                local outcome=require('tasks.'..name..'.task').run(ctx)
                log.write(ctx,'task_result',name..' status='..outcome.status..' reason='..(outcome.reason or ''))
                if outcome.status~='done' then
                    complete=false
                    log.write(ctx,'error','task='..name..' status='..outcome.status..' reason='..(outcome.reason or ''))
                    snapshot.capture(ctx,'task_'..name..'_incomplete')
                    if outcome.status=='paused' or outcome.status=='blocked' or outcome.status=='failed' then
                        log.write(ctx,'summary','all_roles_done=false selected_done=false daily_done=false reason='..name..'_'..outcome.status)
                        return
                    end
                end
                if not navigation.finish_account(ctx) then
                    log.write(ctx,'task_result','navigation status=blocked reason=return_home_not_verified')
                    log.write(ctx,'error','task=navigation reason=return_home_not_verified')
                    snapshot.capture(ctx,'return_home_not_verified')
                    complete=false; break
                end
            end
        end
        if complete then completed=completed+1 else failed=failed+1 end
        log.write(ctx,'account_result','status='..(complete and 'done' or 'incomplete'))
        -- Continue other roles only after proving the previous scene can be left.
        if not navigation.finish_account(ctx) then
            log.write(ctx,'summary','all_roles_done=false selected_done=false daily_done=false reason=return_home_not_verified')
            return
        end
    end
    local full={}
    for _,name in ipairs(selected) do full[name]=true end
    local done=completed==#accounts and failed==0
    local all=done and not selection
    local daily=all and full.shimen and full.zhuagui and full.dungeon and full.rewards or false
    log.write(ctx,'summary','scope='..(selection and 'selected_roles' or 'roles')..' roles_expected='..#accounts..' roles_completed='..completed..
        ' all_roles_done='..tostring(all)..' selected_done='..tostring(done)..' daily_done='..tostring(daily))
end
return M
