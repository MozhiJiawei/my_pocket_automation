"""Production profiling preserves return values/errors and keeps diagnostics separate."""
from pathlib import Path
import tempfile
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

class ProfileTest(unittest.TestCase):
    @staticmethod
    def make_lua():
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        return lua

    def installed_lua(self):
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
        return lua

    def test_wrapped_functions_preserve_nil_returns_and_exceptions(self):
        lua=self.installed_lua()
        self.assertEqual(lua.execute("return require('common.detector').find()"),(None,'reason',False))
        ok,error=lua.execute("return pcall(require('tasks.zhuagui.find').solve)")
        self.assertFalse(ok)
        self.assertIn('recognition_fault',error)
        lua.execute("require('dfx.profile').flush(ctx)")
        self.assertTrue(any('errors=1' in line for line in lua.globals().events.values()))

    def test_leaf_profiling_does_not_read_files_or_mix_role_counters(self):
        lua=self.installed_lua()
        lua.execute('''
            local open=io.open; wall_reads=0
            io.open=function(...) wall_reads=wall_reads+1;return open(...) end
            for i=1,2000 do
                require('common.detector').find()
                require('tasks.zhuagui.pages').state()
            end
            ctx.account={alias='second'};require('common.detector').find()
            ctx.account={alias='fake'};require('common.detector').find()
        ''')
        self.assertEqual(lua.globals().wall_reads,0)
        self.assertEqual(lua.globals().ctx.profile.stats['fake:recognition'].count,2001)
        self.assertEqual(lua.globals().ctx.profile.stats['second:recognition'].count,1)
        lua.execute("require('dfx.profile').flush(ctx)")
        recognition=[line for line in lua.globals().events.values() if ':recognition ' in line]
        self.assertTrue(all('cpu_ms=' in line and 'wall_ms=' not in line for line in recognition))

    def test_wall_clock_is_still_measured_at_task_boundaries(self):
        lua=self.installed_lua()
        lua.execute('''
            local open=io.open; wall_reads=0
            io.open=function(...) wall_reads=wall_reads+1;return open(...) end
            require('tasks.zhuagui.task').run()
        ''')
        self.assertEqual(lua.globals().wall_reads,2)
        self.assertFalse(lua.globals().ctx.profile.stats['fake:task.zhuagui'].cpu_only)

    def test_error_profile_and_debug_files_are_separate_and_debug_has_no_image(self):
        lua=self.make_lua()
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).as_posix()
            lua.execute(f"ctx={{run_id='fake',config={{}},log_path='{base}/debug.log',error_path='{base}/error.log',profile_path='{base}/profile.log'}};nLog=function() end")
            lua.execute("ctx.profile={started=100,clock=function() return 350 end};local l=require('dfx.log');l.write(ctx,'task_start','dungeon');l.write(ctx,'state','battle');l.write(ctx,'tap','noise');l.write(ctx,'error','fault');l.write(ctx,'profile','timing');require('dfx.snapshot').capture(ctx,'before','debug')")
            self.assertIn('[elapsed_ms=250][task_start] dungeon',Path(folder,'debug.log').read_text())
            self.assertNotIn('battle',Path(folder,'debug.log').read_text())
            self.assertNotIn('noise',Path(folder,'debug.log').read_text())
            self.assertIn('fault',Path(folder,'error.log').read_text())
            self.assertIn('timing',Path(folder,'profile.log').read_text())


class FindProfileTest(unittest.TestCase):
    def trace_lua(self):
        lua=ProfileTest.make_lua()
        lua.execute('''
            now=0;clock_reads=0;events={};held=false
            ctx={profile={clock=function() clock_reads=clock_reads+1;return now end},
                recognition_materials={task='shimen',account='first',prefix='shimen_find_r001_',
                    paths={'/res/first.png'},captured=false}}
            package.preload['dfx.log']=function() return {write=function(c,event,line)
                if event=='profile' then events[#events+1]=line end end} end
            keepScreen=function(value) held=value end
            package.preload['common.detector']=function() return {present=function(feature)
                if feature=='title' then return true end
                if native_error then error('native_error') end
                return false
            end} end
            p=require('dfx.find_profile');p.start(ctx)
        ''')
        return lua

    def test_stage_timing_reads_are_constant_and_no_log_is_written_during_scan(self):
        lua=self.trace_lua()
        lua.execute('''
            function scan(count)
                local features={};for i=1,count do features[i]={} end
                local before=clock_reads
                p.call(ctx,'scan',1,require('common.find_items').scan,features,'title',nil,nil,nil,p.row(ctx,1))
                return clock_reads-before
            end
        ''')
        self.assertEqual(lua.eval('scan')(1),2)
        self.assertEqual(lua.eval('scan')(2000),2)
        self.assertEqual(len(lua.globals().events),0)
        row=lua.globals().ctx.recognition_materials.find_profile.rows[1]
        self.assertEqual(row.candidates,2001)
        self.assertEqual(row.searches,2001)

    def test_stage_wall_time_includes_wait_and_records_actual_targets(self):
        lua=self.trace_lua()
        lua.execute('''
            p.call(ctx,'stable',1,function() now=now+300 end)
            package.preload['common.detector']=nil
            package.loaded['common.detector']={find=function() return {x=100,y=600,tap_offset={10,20}} end}
            mSleep=function(ms) now=now+ms end;tap=function() end
            package.preload['dfx.snapshot']=function() return {capture=function() end} end
            p.call(ctx,'tap',1,require('common.device').tap,ctx,{},'find_item')
            p.result(ctx,false,'find_click_not_confirmed')
            p.flush(ctx,ctx.recognition_materials,'find_click_not_confirmed')
        ''')
        lines=list(lua.globals().events.values())
        self.assertEqual(len(lines),2)
        self.assertIn('wall_ms=1500',lines[0])
        self.assertIn('other_ms=0',lines[0])
        self.assertIn('targets=110,620',lines[1])
        self.assertIn('stable=0,300,',lines[1])
        self.assertIn('tap=300,1200,',lines[1])

    def test_native_failure_releases_frame_and_remains_in_failure_trace(self):
        lua=self.trace_lua()
        ok,error=lua.execute('''
            native_error=true
            return pcall(p.call,ctx,'scan',1,require('common.find_items').scan,{{}},'title',nil,nil,nil,p.row(ctx,1))
        ''')
        self.assertFalse(ok)
        self.assertIn('native_error',error)
        self.assertFalse(lua.globals().held)
        lua.execute("p.stop(ctx);p.flush(ctx,ctx.recognition_materials,'script_failed')")
        lines=list(lua.globals().events.values())
        self.assertIn('reason=script_failed',lines[0])
        self.assertIn('error=scan',lines[1])

    def test_finished_recognition_is_frozen_before_delivery_dialogue(self):
        lua=self.trace_lua()
        lua.execute('''
            package.loaded['common.detector']={find=function() return {x=100,y=600,tap_offset={0,0}} end}
            package.preload['dfx.snapshot']=function() return {capture=function() end} end
            mSleep=function(ms) now=now+ms end;tap=function() end
            local device=require('common.device')
            p.call(ctx,'tap',1,device.tap,ctx,{},'find_item')
            p.result(ctx,true,'find_completed')
            package.loaded['common.detector'].find=function() return {x=800,y=1200,tap_offset={0,0}} end
            p.call(ctx,'tap',1,device.tap,ctx,{},'story_dialogue')
            p.target(ctx,1,700,1100)
            p.flush(ctx,ctx.recognition_materials,'shimen_story_dialogue_not_changed')
        ''')
        lines=list(lua.globals().events.values())
        self.assertIn('wall_ms=1200',lines[0])
        self.assertIn('targets=100,600',lines[1])
        self.assertNotIn('800,1200',lines[1])
        self.assertNotIn('700,1100',lines[1])

if __name__=='__main__':unittest.main()
