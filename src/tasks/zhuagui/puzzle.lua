-- Four identified pieces; each click pair swaps one piece into its target cell.
local detector=require('common.detector')
local device=require('common.device')
local assets=require('tasks.zhuagui.assets.puzzle')
local M={}
function M.read()
    keepScreen(true)
    local ok,name,locations=pcall(function()
        if not detector.present(assets.title) then return nil end
        for family,features in pairs(assets.families) do
            local positions,occupied={},{}
            for piece,feature in ipairs(features) do
                local found=detector.find(feature)
                if not found then break end
                for cell,box in ipairs(assets.cells) do
                    if found.x>=box[1] and found.x<box[3] and found.y>=box[2] and found.y<box[4] then
                        if occupied[cell] then return nil end
                        positions[piece]=cell;occupied[cell]=true
                        break
                    end
                end
            end
            if #positions==4 then return family,positions end
        end
    end)
    keepScreen(false)
    if not ok then error(name,0) end
    return name,locations
end
function M.solve(ctx)
    if not detector.present(assets.title) then return false,'puzzle_page_changed' end
    for _=1,3 do
        local family,locations=M.read()
        if not family then return false,'puzzle_tiles_unrecognized' end
        local wanted,destination
        for piece,cell in ipairs(locations) do if piece~=cell then wanted=piece;break end end
        local features=assets.families[family]
        if not wanted then
            if not device.tap(ctx,features[1],'puzzle_confirm_ordered') then return false,'puzzle_target_changed' end
            if detector.present(assets.title) and not device.tap(ctx,features[1],'puzzle_confirm_ordered') then return false,'puzzle_target_changed' end
            local done=device.wait(function() return not detector.present(assets.title) end,10,300)
            return done,done and 'puzzle_solved' or 'puzzle_completion_not_verified'
        end
        for piece,cell in ipairs(locations) do if cell==wanted then destination=piece;break end end
        if not device.tap(ctx,features[wanted],'puzzle_select_piece') then return false,'puzzle_target_changed' end
        if not detector.present(assets.title) then return true,'puzzle_solved' end
        if not device.tap(ctx,features[destination],'puzzle_place_piece') then return false,'puzzle_target_changed' end
        if not device.wait(function()
            if not detector.present(assets.title) then return true end
            local next_family,next_locations=M.read()
            return next_family==family and next_locations[wanted]==wanted
        end,10,300) then return false,'puzzle_swap_not_verified' end
        if not detector.present(assets.title) then return true,'puzzle_solved' end
    end
    return false,'puzzle_action_limit'
end
return M
