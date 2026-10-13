local M={}
function M.read(region)
    if require('common.screen').size()~=900 then return nil end
    local glyphs={}
    for digit=0,9 do
        local ok,value=pcall(require,'tasks.zhuagui.assets.digits.d' .. digit)
        if ok then glyphs[digit]={value} end
    end
    local ok,variants=pcall(require,'tasks.zhuagui.assets.digits.variants')
    if ok then
        for digit,items in pairs(variants) do
            glyphs[digit]=glyphs[digit] or {}
            for _,glyph in ipairs(items) do glyphs[digit][#glyphs[digit]+1]=glyph end
        end
    end
    local x1,y1,x2,y2=table.unpack(region or {740,208,806,229})
    local columns,rows={},{}
    keepScreen(true)
    for y=y1,y2 do
        rows[y]={}
        for x=x1,x2 do
            local c=getColor(x,y)
            local r,g,b=math.floor(c/65536)%256,math.floor(c/256)%256,c%256
            local on=g>140 and r<150 and b<120
            rows[y][x]=on
            columns[x]=columns[x] or on
        end
    end
    keepScreen(false)
    local digits,left={},nil
    for x=x1,x2+1 do
        if columns[x] and not left then left=x end
        if left and not columns[x] then
            local width=x-left
            local best,best_error=nil,1
            for digit,items in pairs(glyphs) do
            for _,glyph in ipairs(items) do
                if #glyph[1]==width then
                    local errors=0
                    for y=y1,y2 do
                        for px=left,x-1 do
                            if rows[y][px]~=(glyph[y-y1+1]:sub(px-left+1,px-left+1)=='1') then errors=errors+1 end
                        end
                    end
                    local ratio=errors/((y2-y1+1)*width)
                    if ratio<best_error then best,best_error=digit,ratio end
                end
            end
            end
            if best==nil or best_error>0.06 then return nil end
            digits[#digits+1]=tostring(best)
            left=nil
        end
    end
    if #digits==0 or #digits>2 then return nil end
    return tonumber(table.concat(digits))
end
return M
