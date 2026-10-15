"""Production profiling preserves return values/errors and keeps diagnostics separate."""
from pathlib import Path
import tempfile
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

class ProfileTest(unittest.TestCase):
    def make_lua(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        return lua

    def test_wrapped_functions_preserve_nil_returns_and_exceptions(self):
        lua=self.make_lua()
        lua.execute('''
            events={};ctx={config={profile=true},account={alias='fake'}}
            package.preload['dfx.log']=function() return {write=function(c,e,d) events[#events+1]=d end} end
            for _,name in ipairs({'common.detector','tasks.zhuagui.pages','tasks.dungeon.pages',
                'tasks.zhuagui.find','common.device','common.navigation','tasks.zhuagui.task','tasks.dungeon.task',
                'tasks.shimen.pages','tasks.rewards.pages','tasks.shimen.find','tasks.shimen.puzzle',
                'tasks.shimen.task','tasks.rewards.task'}) do
                package.preload[name]=function() return {
                    find=function() return nil,'reason',false end,state=function() return 'page' end,
                    solve=function() error('recognition_fault') end,tap=function() return true end,
                    swipe=function() return true end,prepare_recorded=function() return true end,run=function() return {} end}
                end
            end
            require('dfx.profile').install(ctx)
        ''')
        self.assertEqual(lua.execute("return require('common.detector').find()"),(None,'reason',False))
        ok,error=lua.execute("return pcall(require('tasks.zhuagui.find').solve)")
        self.assertFalse(ok)
        self.assertIn('recognition_fault',error)
        lua.execute("require('dfx.profile').flush(ctx)")
        self.assertTrue(any('errors=1' in line for line in lua.globals().events.values()))

    def test_error_profile_and_debug_files_are_separate_and_debug_has_no_image(self):
        lua=self.make_lua()
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).as_posix()
            lua.execute(f"ctx={{run_id='fake',config={{}},log_path='{base}/debug.log',error_path='{base}/error.log',profile_path='{base}/profile.log'}};nLog=function() end")
            lua.execute("ctx.profile={started=100,clock=function() return 350 end};local l=require('dfx.log');l.write(ctx,'state','battle');l.write(ctx,'tap','noise');l.write(ctx,'error','fault');l.write(ctx,'profile','timing');require('dfx.snapshot').capture(ctx,'before','debug')")
            self.assertIn('battle',Path(folder,'debug.log').read_text())
            self.assertIn('[elapsed_ms=250][state] battle',Path(folder,'debug.log').read_text())
            self.assertNotIn('noise',Path(folder,'debug.log').read_text())
            self.assertIn('fault',Path(folder,'error.log').read_text())
            self.assertIn('timing',Path(folder,'profile.log').read_text())

if __name__=='__main__':unittest.main()
