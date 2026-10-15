"""All 24 four-cell permutations use at most three verified swaps, no retry."""
import itertools
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

class PuzzleSwapTest(unittest.TestCase):
    def make_lua(self,order):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        lua.execute('''
            held=false; taps=0; selected=nil; finished=false; corrupt=false
            puzzle_logs={}
            package.preload['dfx.log']=function() return {write=function(c,event,detail)
                puzzle_logs[#puzzle_logs+1]={event,detail}
            end} end
            local cells={{0,0,10,10},{10,0,20,10},{0,10,10,20},{10,10,20,20}}
            local features={{id=1},{id=2},{id=3},{id=4}}
            package.preload['tasks.zhuagui.assets.puzzle']=function() return {title={title=true},cells=cells,families={fake=features}} end
            keepScreen=function(value) held=value end
            package.preload['common.detector']=function() return {
                present=function() return not finished end,
                find=function(f)
                    if corrupt then return nil end
                    for slot,piece in ipairs(board) do
                        if piece==f.id then return {x=cells[slot][1]+5,y=cells[slot][2]+5} end
                    end
                end}
            end
            package.preload['common.device']=function() return {
                tap=function(c,f)
                    assert(not held);taps=taps+1
                    if selected then
                        local first,second
                        for slot,piece in ipairs(board) do
                            if piece==selected then first=slot end
                            if piece==f.id then second=slot end
                        end
                        board[first],board[second]=board[second],board[first];selected=nil
                        finished=true;for slot,piece in ipairs(board) do if piece~=slot then finished=false end end
                    else selected=f.id end
                    return true
                end,
                wait=function(predicate) return predicate() end}
            end
        ''')
        lua.globals().board=lua.table_from(order)
        return lua

    def test_every_permutation(self):
        for order in itertools.permutations((1,2,3,4)):
            with self.subTest(order=order):
                lua=self.make_lua(order)
                ok,reason=lua.execute("return require('tasks.zhuagui.puzzle').solve({})")
                self.assertTrue(ok,reason)
                self.assertEqual(lua.globals().puzzle_logs[1][2],'family=fake recognition=all_tiles_matched')
                self.assertLessEqual(lua.globals().taps,6)
                self.assertEqual(list(lua.globals().board.values()),[1,2,3,4])

    def test_unrecognized_board_sends_no_click(self):
        lua=self.make_lua((3,1,2,4));lua.execute('corrupt=true')
        self.assertEqual(lua.execute("return require('tasks.zhuagui.puzzle').solve({})"),(False,'puzzle_tiles_unrecognized'))
        self.assertEqual(lua.globals().taps,0)
        self.assertFalse(lua.globals().held)

if __name__=='__main__':unittest.main()
