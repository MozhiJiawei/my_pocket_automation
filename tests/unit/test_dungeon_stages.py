"""A final-stage marker alone must never prove all five stages completed."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class DungeonStagesTest(unittest.TestCase):
    def test_requires_each_of_five_completed_markers(self):
        for dungeon in ('wuji','chechi'):
            for missing in (None,-550,-412,-275,-138,0):
                with self.subTest(dungeon=dungeon,missing=missing):
                    lua=LuaRuntime(unpack_returned_tuples=True)
                    lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
                    lua.execute('''
                        package.preload['common.detector']=function() return {
                            present=function(f)
                                if f==definition.title then return true end
                                if f.base==definition.final_done.base and f.offsets==definition.final_done.offsets then
                                    return f.region[2]~=missing_y
                                end
                                return false
                            end
                        } end
                    ''')
                    pages=lua.eval("require('tasks.dungeon.pages')")[0]
                    definition=pages.definitions[dungeon]
                    lua.globals().definition=definition
                    lua.globals().missing_y=None if missing is None else definition.final_done.region[2]+missing
                    self.assertEqual(pages.state(),dungeon+('_done' if missing is None else '_active'))
