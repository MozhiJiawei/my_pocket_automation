"""Actual legacy solver: unique identities, missing tile and verified swaps."""
from pathlib import Path
import itertools,unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class ShimenPuzzleTest(unittest.TestCase):
    def test_reviewed_completed_card_remains_identifiable_at_scroll_positions(self):
        import numpy as np
        from scripts.perception.lib.corpus import read_answers
        from tests.support.touchsprite_adapter import Screen
        from tests.support.lua_runtime import Runtime
        folder=ROOT/'testdata/师门/页面/今日完成任务卡片'
        expected=read_answers(folder)['预期']['画面.png']['page']
        original=Screen.read(folder/'画面.png').frame
        for shift in (0,200,400,600):
            with self.subTest(scroll_pixels=shift):
                frame=original.copy()
                frame[304:1420]=np.roll(original[304:1420],-shift,axis=0)
                runtime=Runtime(Screen(frame))
                try:self.assertEqual(runtime.require('tasks.shimen.pages').state(),expected)
                finally:runtime.close()

    def test_reviewed_puzzles_all_tiles_match_in_every_permutation(self):
        from scripts.perception.lib.corpus import read_answers
        from tests.support.touchsprite_adapter import Screen
        from tests.support.lua_runtime import Runtime
        for folder in sorted((ROOT/'testdata/师门/拼图').iterdir()):
            if not folder.is_dir():continue
            for filename,answer in read_answers(folder)['预期'].items():
                expected=answer['puzzle_locations']
                original=Screen.read(folder/filename).frame
                runtime=Runtime(Screen(original))
                try:
                    self.assertEqual(runtime.require('tasks.shimen.puzzle').identify(),folder.name)
                    assets=runtime.require('tasks.shimen.assets.legacy_puzzles')
                    boxes=[tuple(b.values()) for b in assets.cells.values()]
                finally:runtime.close()
                tiles=[original[y1:y2,x1:x2].copy() for x1,y1,x2,y2 in boxes]
                for slots in itertools.permutations(range(1,5)):
                    with self.subTest(family=folder.name,image=filename,slots=slots):
                        frame=original.copy()
                        for piece,cell in enumerate(slots,1):
                            x1,y1,x2,y2=boxes[cell-1]
                            frame[y1:y2,x1:x2]=tiles[expected[piece-1]-1]
                        runtime=Runtime(Screen(frame))
                        try:
                            positions,reason=runtime.require('tasks.shimen.puzzle').read(folder.name)
                            self.assertEqual(reason,'all_tiles_matched',slots)
                            self.assertEqual(list(positions.values()),list(slots))
                        finally:runtime.close()

    def runtime(self,slots,missing=1):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        lua.globals().slots=lua.table_from(slots)
        lua.globals().missing=missing
        lua.execute('''
            visible=true;clicks={};selected=nil
            assets={cells={{0,0,100,100},{100,0,200,100},{0,100,100,200},{100,100,200,200}},families={tiger={}}}
            for i=1,4 do assets.families.tiger[i]={base=i,bounds={0,0,0,0}} end
            package.preload['tasks.shimen.assets.legacy_puzzles']=function() return assets end
            package.preload['tasks.shimen.pages']=function() return {features={puzzle={base=99}}} end
            package.preload['common.detector']=function() return {
                find=function(f) if visible and f.base==99 then return {x=0,y=0} end end,
                present=function(f)
                    if f.base==99 then return visible end
                    if f.base==missing or (missing_two and f.base==missing_two) then return false end
                    for cell,box in ipairs(assets.cells) do
                        if f.region[1]==box[1] and f.region[2]==box[2] then
                            return visible and (slots[f.base]==cell or ambiguous_cell==cell)
                        end
                    end
                    return false
                end} end
            package.preload['common.device']=function() return {
                tap=function(c,f)
                    local x,y=f.tap_offset[1],f.tap_offset[2]
                    local cell=1+(x>=100 and 1 or 0)+(y>=100 and 2 or 0)
                    table.insert(clicks,cell)
                    if not selected then selected=cell else
                        if not freeze then
                            for piece=1,4 do
                                if slots[piece]==selected then slots[piece]=cell
                                elseif slots[piece]==cell then slots[piece]=selected end
                            end
                        end
                        selected=nil
                        local ordered=true
                        for i=1,4 do if slots[i]~=i then ordered=false end end
                        if ordered then visible=false end
                    end
                    return true
                end,
                wait=function(predicate) return predicate() end} end
            package.preload['dfx.log']=function() return {write=function() end} end
            keepScreen=function() end
        ''')
        return lua,lua.eval("require('tasks.shimen.puzzle')")[0]

    def test_all_permutations_with_one_unrecognized_tile(self):
        for slots in itertools.permutations(range(1,5)):
            with self.subTest(slots=slots):
                lua,module=self.runtime(slots)
                ok,reason=module.solve(lua.table(), 'tiger')
                self.assertTrue(ok,reason)
                self.assertFalse(lua.globals().visible)
                self.assertLessEqual(len(lua.globals().clicks),6)

    def test_two_missing_tiles_stop_without_clicks(self):
        lua,module=self.runtime((3,2,4,1))
        lua.execute('missing_two=2')
        ok,reason=module.solve(lua.table(),'tiger')
        self.assertFalse(ok);self.assertEqual(reason,'puzzle_tiles_unrecognized')
        self.assertEqual(len(lua.globals().clicks),0)

    def test_duplicate_cell_match_stops_without_clicks(self):
        lua,module=self.runtime((3,2,4,1))
        lua.execute('ambiguous_cell=3')
        ok,reason=module.solve(lua.table(),'tiger')
        self.assertFalse(ok);self.assertEqual(reason,'puzzle_tiles_ambiguous')
        self.assertEqual(len(lua.globals().clicks),0)

    def test_swap_postcondition_must_change_position(self):
        lua,module=self.runtime((3,2,4,1))
        lua.execute('freeze=true')
        ok,reason=module.solve(lua.table(),'tiger')
        self.assertFalse(ok);self.assertEqual(reason,'puzzle_swap_not_verified')
        self.assertEqual(len(lua.globals().clicks),2)

    def test_unknown_family_never_clicks(self):
        lua,module=self.runtime((3,2,4,1))
        ok,reason=module.solve(lua.table(),'unknown')
        self.assertFalse(ok);self.assertEqual(reason,'puzzle_family_unknown')
        self.assertEqual(len(lua.globals().clicks),0)

    def test_auto_family_uses_unique_old_signatures(self):
        lua,module=self.runtime((3,2,4,1))
        ok,reason=module.solve(lua.table(),'auto')
        self.assertTrue(ok,reason)

    def test_auto_family_ambiguity_never_clicks(self):
        lua,module=self.runtime((3,2,4,1))
        lua.execute('assets.families.other=assets.families.tiger')
        ok,reason=module.solve(lua.table(),'auto')
        self.assertFalse(ok);self.assertEqual(reason,'puzzle_family_ambiguous')
        self.assertEqual(len(lua.globals().clicks),0)

    def test_imported_resources_have_four_bounded_features_each(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        data=lua.execute((ROOT/'src/tasks/shimen/assets/legacy_puzzles.lua').read_text(encoding='utf-8'))
        self.assertEqual(len(list(data.families.keys())),31)
        self.assertIn('老虎',data.families)
        self.assertIn('地狱战神',data.families)
        self.assertIn('雨师',data.families)
        self.assertIn('骨精灵',data.families)
        for features in data.families.values():
            self.assertEqual(len(features),4)
            for feature in features.values():
                self.assertEqual(feature.width,900)
                self.assertEqual(feature.degree,90)
                self.assertLess(feature.bounds[3]-feature.bounds[1],292)
                self.assertLess(feature.bounds[4]-feature.bounds[2],370)
