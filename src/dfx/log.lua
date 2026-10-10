local M = {}
function M.write(ctx, event, detail)
    local line = string.format('[daily][%s][%s] %s', ctx.run_id, event, tostring(detail or ''))
    nLog(line)
    local file = assert(io.open(ctx.log_path, 'a'))
    file:write(line .. '\n')
    file:close()
end
return M
