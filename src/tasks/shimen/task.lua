local M = {}
function M.observe(ctx)
    require('dfx.log').write(ctx,'shimen_observe','collection_phase no_actions=true')
end
function M.run(ctx)
    M.observe(ctx)
    return {status = 'not_implemented', reason = 'collection_phase_runtime_not_enabled'}
end
return M
