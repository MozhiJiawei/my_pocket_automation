local M={}

function M.automatic(ctx)
    return ctx.config.step=='daily' and ctx.config.automatic_dungeons==true and ctx.config.dungeons==nil
end

local function completion_key(ctx)
    return ctx.account.claim_dungeon_rewards==true and 'dungeonsclaimed' or 'dungeonscleared'
end

function M.completed(ctx)
    if not M.automatic(ctx) then return nil end
    local completion=require('completion')
    return completion.read(ctx,completion_key(ctx)) or
        (ctx.account.claim_dungeon_rewards~=true and completion.read(ctx,'dungeonsclaimed'))
end

function M.item_cleared(ctx,id)
    if ctx.account and ctx.account.claim_dungeon_rewards~=true then
        return require('completion').read(ctx,id..'cleared')
    end
end

function M.mark_item_cleared(ctx,id)
    if ctx.config.step=='daily' and ctx.account.claim_dungeon_rewards~=true then
        require('completion').write(ctx,id..'cleared','done','reward_intentionally_unclaimed')
    end
end

function M.rewards_scope_complete(ctx)
    if M.automatic(ctx) then return not not M.completed(ctx) end
    local completion=require('completion')
    for _,id in ipairs(ctx.config.dungeons or {'wuji','chechi'}) do
        if not completion.read(ctx,id) and not M.item_cleared(ctx,id) then return false end
    end
    return true
end

function M.resolve(ctx)
    if not M.automatic(ctx) then return ctx.config.dungeons or {'wuji','chechi'} end
    if not ctx.identity_verified then return nil,'dungeon_scope_identity_not_verified' end
    local date=ctx.config.business_date
    if not date or date~=os.date('%Y%m%d') then return nil,'dungeon_scope_date_not_verified' end
    local verified=ctx.dungeon_scope
    if verified and verified.account==ctx.account and verified.date==date then return verified.targets end
    if not require('tasks.rewards.task').verify_task_completed(ctx,'zhuagui') then
        return nil,'zhuagui_not_verified_complete'
    end
    local count,reason=require('tasks.rewards.inventory').ghost_count(ctx)
    if count~=2 and count~=3 then return nil,reason or 'ghost_gourd_count_not_verified' end
    local targets={'wuji','heifeng','shuilu','chechi'}
    if count==2 then targets[#targets+1]='pingding' end
    ctx.dungeon_scope={account=ctx.account,date=date,targets=targets}
    require('dfx.log').write(ctx,'dungeon_scope','ghost_gourds='..count..' selected='..table.concat(targets,','))
    return targets
end

function M.mark_complete(ctx)
    if M.automatic(ctx) and ctx.dungeon_scope and ctx.dungeon_scope.account==ctx.account and
        ctx.dungeon_scope.date==ctx.config.business_date then
        require('completion').write(ctx,completion_key(ctx),'done','selected_dungeons_verified')
    end
end

return M
