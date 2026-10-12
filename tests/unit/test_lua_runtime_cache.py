"""Bytecode reuse must not reuse mutable Lua state or hide source changes."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import numpy as np
from tests.support.lua_runtime import Runtime,compiled_source,versioned_module_code
from tests.support.touchsprite_adapter import Screen


class LuaRuntimeCacheTest(unittest.TestCase):
    def test_module_tables_remain_isolated_between_frames(self):
        compiled_source.cache_clear()
        versioned_module_code.cache_clear()
        first=Runtime(Screen(np.zeros((2,2,3),dtype=np.uint8)))
        second=Runtime(Screen(np.zeros((2,2,3),dtype=np.uint8)))
        a=first.require('tasks.zhuagui.assets.catalog')
        b=second.require('tasks.zhuagui.assets.catalog')
        original=b['兵器'][1]['base']
        a['兵器'][1]['base']=0
        self.assertEqual(b['兵器'][1]['base'],original)
        self.assertGreater(versioned_module_code.cache_info().hits,0)

    def test_changed_source_is_recompiled_and_preload_keeps_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'src').mkdir()
            file=root/'src/example.lua';file.write_text('return {answer=1}',encoding='utf-8')
            with patch('tests.support.lua_runtime.ROOT',root):
                first=Runtime(Screen(np.zeros((2,2,3),dtype=np.uint8)))
                self.assertEqual(first.require('example')['answer'],1)
                file.write_text('return {answer=2}',encoding='utf-8')
                second=Runtime(Screen(np.zeros((2,2,3),dtype=np.uint8)))
                self.assertEqual(second.require('example')['answer'],2)
                third=Runtime(Screen(np.zeros((2,2,3),dtype=np.uint8)))
                third.lua.execute("package.preload['example']=function() return {answer=3} end")
                self.assertEqual(third.require('example')['answer'],3)
