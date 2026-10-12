"""Find the approved task entry independently of its row or scroll position."""
import unittest
import numpy as np
from scripts.perception.lib.corpus import load_cases, validate
from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen


class TaskEntryTest(unittest.TestCase):
    def test_task_card_after_recommended_dungeon_insertion(self):
        case=next(c for c in load_cases('zhuagui') if 'zhuagui_entry' in c['truth'])
        runtime=Runtime(Screen.read(validate(case)))
        feature=runtime.require('tasks.zhuagui.assets.task_card')
        self.assertTrue(runtime.plan_tap(runtime.lua.table(),feature,'open_ghost_entry'))
        x,y=runtime.actions[-1]['point']
        x1,y1,x2,y2=case['truth']['zhuagui_entry']['value']
        self.assertTrue(x1<=x<=x2 and y1<=y<=y2)

    def test_entry_follows_translated_card_instead_of_a_fixed_row(self):
        case=next(c for c in load_cases('zhuagui') if 'zhuagui_entry' in c['truth'])
        original=Screen.read(validate(case)).frame
        x1,y1,x2,y2=case['truth']['zhuagui_entry']['value']
        card=original[y1:y2,x1:x2].copy()
        for left,top in ((50,330),(50,625),(80,1000)):
            with self.subTest(position=(left,top)):
                frame=original.copy();frame[300:1420]=(215,204,185)
                frame[top:top+card.shape[0],left:left+card.shape[1]]=card
                runtime=Runtime(Screen(np.ascontiguousarray(frame)))
                feature=runtime.require('tasks.zhuagui.assets.task_card')
                self.assertTrue(runtime.plan_tap(runtime.lua.table(),feature,'entry'))
                x,y=runtime.actions[-1]['point']
                self.assertTrue(left<=x<=left+card.shape[1] and top<=y<=top+card.shape[0])


if __name__=='__main__':unittest.main()
