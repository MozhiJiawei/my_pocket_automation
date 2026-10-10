"""Actual action revalidation against explicit image sequences; no fake detector."""
import json
from pathlib import Path
import unittest
from scripts.perception.lib.corpus import load_cases, image_path
from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen


class FrameReplayTest(unittest.TestCase):
    def test_capture_transition_revalidates_target_before_tapping(self):
        index={c['id']:c for c in load_cases('zhuagui')}
        folder=Path(__file__).resolve().parents[2]/'testdata/zhuagui'
        scenarios=json.loads((folder/'sequences.json').read_text(encoding='utf-8'))
        for scenario in scenarios:
            with self.subTest(scenario=scenario['id']):
                frames=[index[key] for key in scenario['frames']]
                def transition(runtime,label):
                    runtime.screen=Screen.read(image_path(frames[1]))
                runtime=Runtime(Screen.read(image_path(frames[0])),capture_hook=transition)
                source=runtime.require('tasks.zhuagui.assets.icon_snake_wine')
                feature=runtime.lua.table_from(dict(source.items()))
                # The task expands the calibrated feature's original ROI for search.
                feature['region']=runtime.lua.table_from([65,540,825,1405])
                self.assertIsNotNone(runtime.require('common.detector').find(feature))
                result=runtime.require('common.device').tap(runtime.lua.table(),feature,'replay')
                self.assertEqual(bool(result),scenario['expected']['tap_return'])
                if 'actions' in scenario['expected']:
                    self.assertEqual(runtime.actions,scenario['expected']['actions'])
                else:
                    self.assertEqual(len(runtime.actions),1)
                    x,y=runtime.actions[0]['point']
                    self.assertTrue(any(x1<=x<x2 and y1<=y<y2 for x1,y1,x2,y2 in scenario['expected']['allowed_regions']))

if __name__=='__main__': unittest.main()
