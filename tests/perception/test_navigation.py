"""Real role-switch failure, retaining only the public button."""
import json
from pathlib import Path
import unittest
from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen

ROOT=Path(__file__).resolve().parents[2]

class NavigationRecognitionTest(unittest.TestCase):
    def test_loaded_role_tile_corners_remain_recognizable(self):
        folder=ROOT/'testdata/导航/角色卡片加载完成'
        truth=json.loads((folder/'预期.json').read_text(encoding='utf-8'))
        runtime=Runtime(Screen.read(folder/'画面.png'))
        feature=runtime.require(truth['feature'])
        for rectangle in truth['anchor_regions']:
            with self.subTest(rectangle=rectangle):
                feature['region']=runtime.lua.table_from(rectangle)
                self.assertIsNotNone(runtime.require('common.detector').find(feature))

    def test_switch_button_is_independent_of_role_avatar(self):
        folder=ROOT/'testdata/导航/已登录角色切换按钮'
        truth=json.loads((folder/'预期.json').read_text(encoding='utf-8'))
        runtime=Runtime(Screen.read(folder/'画面.png'))
        feature=runtime.require(truth['feature'])
        found=runtime.require('common.detector').find(feature)
        self.assertIsNotNone(found)
        x1,y1,x2,y2=truth['tap_region']
        self.assertTrue(x1<=found['x']+feature['tap_offset'][1]<=x2 and y1<=found['y']+feature['tap_offset'][2]<=y2)
