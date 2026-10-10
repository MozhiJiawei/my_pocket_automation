"""Conserve every old feature and verify scaling without device inputs."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class LegacyTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path; getScreenSize=function() return 900,1600 end")
        self.adapter=self.lua.eval("require('tasks.zhuagui.legacy')")[0]
        self.data=self.adapter['data']

    def test_every_original_target_item_and_puzzle_is_preserved(self):
        text=(ROOT/'参考代码/zhuagui.lua').read_text(encoding='utf-8')
        items=text[text.index('local bb = {}'):text.index('function XunWu')]
        puzzle=text[text.index('\ttt["鼎1"]'):text.index('\n\tlocal name = nil',text.index('function ZhuaGuiPintu'))]
        original=self.lua.execute(items+'\nlocal tt={}\n'+puzzle+'\nreturn {targets=bb,items=cc,puzzles=tt,slots=mm}')
        def plain(value):
            if hasattr(value,'keys'): return {k:plain(v) for k,v in value.items()}
            return value
        for key in ('targets','items','puzzles','slots'):
            self.assertEqual(plain(self.data[key]),plain(original[key]))
        self.assertEqual(sum(len(v) for v in self.data['items'].values()),113)
        self.assertEqual(sum(len(v) for v in self.data['puzzles'].values()),28)

    def test_item_scales_use_width_and_height_ratios_and_preserve_colors(self):
        features=self.adapter['items']('酒')
        self.assertEqual(len(features),81)
        self.assertEqual([features[i]['legacy_scale'] for i in (1,28,55)],[1.875,2.0,1.75])
        self.assertEqual(features[1]['base'],self.data['items']['酒'][1][1])
        self.assertTrue(features[1]['offsets'].startswith('-7|-2|0x14100b'))
        self.assertEqual(list(features[1]['region'].values()),[65,540,825,1405])

    def test_unsupported_layout_does_not_search(self):
        self.lua.execute('getScreenSize=function() return 720,1280 end')
        self.assertEqual(len(self.adapter['items']('酒')),0)
        self.assertIsNone(self.adapter.target())

    def test_multiple_target_categories_are_rejected(self):
        self.lua.execute('findMultiColorInRegionFuzzy=function() return 100,370 end')
        self.assertEqual(self.adapter.target(),(None,'legacy_target_ambiguous'))


if __name__=='__main__': unittest.main()
