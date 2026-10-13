local M={}
local assets=require('tasks.shimen.assets.legacy_puzzles')
local title=require('tasks.shimen.pages').features.puzzle
local detector=require('common.detector')
local device=require('common.device')
local log=require('dfx.log')
function M.read(family)
    local features=assets.families[family]
    if not features then return nil,'puzzle_family_unknown' end
    keepScreen(true)
    local ok,positions,reason=pcall(function()
        if not detector.present(title) then return nil,'puzzle_page_changed' end
        local locations,occupied,found_count={},{},0
        for piece,feature in ipairs(features) do
            for cell,box in ipairs(assets.cells) do
                local f={};for key,value in pairs(feature) do f[key]=value end
                local b=feature.bounds
                -- All signature points must remain in the same tile.
                f.region={box[1]-b[1],box[2]-b[2],box[3]-1-b[3],box[4]-1-b[4]}
                if detector.present(f) then
                    if locations[piece] or occupied[cell] then return nil,'puzzle_tiles_ambiguous' end
                    locations[piece]=cell;occupied[cell]=true;found_count=found_count+1
                end
            end
        end
        if found_count<3 then return nil,'puzzle_tiles_unrecognized' end
        if found_count==3 then
            local missing_piece,missing_cell
            for i=1,4 do
                if not locations[i] then missing_piece=i end
                if not occupied[i] then missing_cell=i end
            end
            locations[missing_piece]=missing_cell
        end
        return locations,found_count==3 and 'one_tile_inferred' or 'all_tiles_matched'
    end)
    keepScreen(false)
    if not ok then error(positions,0) end
    return positions,reason
end
function M.identify()
    local candidates={}
    local names={};for name in pairs(assets.families) do names[#names+1]=name end
    table.sort(names)
    for _,name in ipairs(names) do
        if M.read(name) then candidates[#candidates+1]=name end
    end
    if #candidates~=1 then return nil,#candidates==0 and 'puzzle_family_unrecognized' or 'puzzle_family_ambiguous' end
    return candidates[1]
end
local function tap_cell(ctx,cell,label)
    local anchor=detector.find(title)
    if not anchor then return false end
    local box=assets.cells[cell]
    local feature={};for key,value in pairs(title) do feature[key]=value end
    feature.region={anchor.x,anchor.y,anchor.x,anchor.y}
    feature.tap_offset={math.floor((box[1]+box[3])/2)-anchor.x,math.floor((box[2]+box[4])/2)-anchor.y}
    return device.tap(ctx,feature,label)
end
function M.solve(ctx,family)
    if family=='auto' then
        local reason;family,reason=M.identify()
        if not family then return false,reason end
    end
    for swap=1,3 do
        local positions,reason=M.read(family)
        if not positions then return false,reason end
        log.write(ctx,'shimen_puzzle','family='..family..' recognition='..reason..' swap='..swap)
        local wanted
        for piece=1,4 do if positions[piece]~=piece then wanted=piece;break end end
        if not wanted then
            if not tap_cell(ctx,1,'shimen_puzzle_confirm') then return false,'puzzle_page_changed' end
            if detector.present(title) and not tap_cell(ctx,1,'shimen_puzzle_confirm') then return false,'puzzle_page_changed' end
            local done=device.wait(function() return not detector.present(title) end,10,200)
            return done,done and 'puzzle_solved' or 'puzzle_completion_not_verified'
        end
        if not tap_cell(ctx,positions[wanted],'shimen_puzzle_select') then return false,'puzzle_page_changed' end
        if not detector.present(title) then return false,'puzzle_unexpected_exit' end
        if not tap_cell(ctx,wanted,'shimen_puzzle_place') then return false,'puzzle_page_changed' end
        if not device.wait(function()
            if not detector.present(title) then return true end
            local next_positions=M.read(family)
            return next_positions and next_positions[wanted]==wanted
        end,10,200) then return false,'puzzle_swap_not_verified' end
        if not detector.present(title) then return true,'puzzle_solved' end
    end
    return false,'puzzle_action_limit'
end
return M
