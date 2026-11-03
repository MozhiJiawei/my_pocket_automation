"""Execute the actual Lua entry with failed diagnostics and fake task modules."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class DeviceDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            events={}; captures={}; fallback={}; fail_log=false; fail_snapshot=false; fail_task=false; fail_init=false
            config={mode='run',step='daily',allow_reward_claim=false,accounts={{alias='fake'}}}
            loadfile=function() return function() return config end end
            init=function() if fail_init then error('initialization_fault') end end
            appIsRunning=function() return 1 end
            nLog=function(line) table.insert(fallback,line) end
            package.preload['TSLib']=function() return {} end
            package.preload['dfx.run']=function() return {new=function(c) return {config=c,run_id='fake'} end} end
            package.preload['dfx.log']=function() return {write=function(ctx,event,detail)
                if fail_log then error('logging_fault') end
                table.insert(events,{event=event,detail=detail})
            end} end
            package.preload['dfx.snapshot']=function() return {capture=function(ctx,label)
                table.insert(captures,label)
                if fail_snapshot then error('screenshot_fault') end
            end} end
            package.preload['common.navigation']=function() return {
                prepare_recorded=function() return true end,
                finish_account=function() return false end
            } end
            for _,name in ipairs({'shimen','zhuagui','dungeon','rewards'}) do
                local task_name=name
                package.preload['tasks.'..name..'.task']=function() return {run=function()
                    if fail_task then error('original_task_fault') end
                    return {status=task_name=='dungeon' and 'done' or 'not_implemented',reason='fake'}
                end} end
            end
        ''')

    def execute(self):
        self.lua.execute((ROOT / 'src/main.lua').read_text(encoding='utf-8'))
        return [(item['event'], item['detail']) for item in self.lua.globals().events.values()]

    def test_screenshot_failure_does_not_prevent_failed_exit_record(self):
        self.lua.execute('fail_snapshot=true')
        events = self.execute()
        self.assertIn(('finished', 'script_failed'), events)
        self.assertTrue(any(event == 'failed' and 'screenshot_fault' in detail for event, detail in events))
        self.assertEqual(list(self.lua.globals().captures.values()), ['start', 'failure'])

    def test_all_file_logging_failures_still_try_snapshot_and_fallback(self):
        self.lua.execute('fail_log=true')
        self.execute()
        self.assertEqual(list(self.lua.globals().captures.values()), ['failure'])
        self.assertTrue(any('diagnostic_log_unavailable' in line for line in self.lua.globals().fallback.values()))
        self.assertTrue(any('[failed]' in line and 'logging_fault' in line for line in self.lua.globals().fallback.values()))

    def test_original_task_error_survives_failure_screenshot_error(self):
        self.lua.execute('fail_task=true')
        # Only the failure capture is broken; the initial capture succeeds.
        self.lua.execute("package.preload['dfx.snapshot']=function() return {capture=function(ctx,label) if label=='failure' then error('secondary_fault') end end} end")
        events = self.execute()
        errors = [detail for event, detail in events if event == 'failed']
        self.assertEqual(len(errors), 1)
        self.assertIn('original_task_fault', errors[0])
        self.assertIn(('finished', 'script_failed'), events)

    def test_init_failure_is_within_error_handler(self):
        self.lua.execute('fail_init=true')
        events = self.execute()
        self.assertIn(('finished', 'script_failed'), events)
        self.assertTrue(any(event == 'failed' and 'initialization_fault' in detail for event, detail in events))

    def test_navigation_failure_is_explicit_task_result(self):
        events = self.execute()
        self.assertIn(('task_result', 'navigation status=blocked reason=return_home_not_verified'), events)
        self.assertIn(('summary', 'daily_done=false reason=return_home_not_verified'), events)

    def configure_owned_ghost_recovery(self,owned):
        self.lua.execute('''
            config.step='complete';config.task='zhuagui';config.verify_role=true
            package.preload['common.navigation']=function() return {prepare_recorded=function() return false end} end
            package.preload['tasks.zhuagui.pages']=function() return {state=function() return 'dialogue' end} end
            package.preload['progress']=function() return {read=function() return recovery_record end} end
        ''')
        if owned:self.lua.execute("recovery_record={status='running'}")

    def test_owned_ghost_recovery_allows_existing_dialogue_only(self):
        self.configure_owned_ghost_recovery(True)
        events=self.execute()
        self.assertTrue(any(event=='screen_resume' for event,_ in events))
        self.assertFalse(any('account status=blocked' in detail for _,detail in events))

    def test_owned_sampling_can_resume_free_dialogue_without_identity(self):
        self.configure_owned_ghost_recovery(True)
        self.lua.execute("config.step='browse'")
        self.assertTrue(any(event=='screen_resume' for event,_ in self.execute()))

    def test_sampling_recovers_visible_dialogue_without_old_state(self):
        self.configure_owned_ghost_recovery(False)
        self.lua.execute("config.step='browse'")
        self.assertTrue(any(event=='screen_resume' for event,_ in self.execute()))

    def test_single_step_recovers_visible_ghost_dialogue_without_navigation(self):
        self.configure_owned_ghost_recovery(False)
        self.lua.execute("config.step='advance'")
        events=self.execute()
        self.assertTrue(any(event=='screen_resume' for event,_ in events))
        self.assertFalse(any('account status=blocked' in detail for _,detail in events))

    def test_ghost_recovers_visible_dialogue_without_old_state(self):
        self.configure_owned_ghost_recovery(False)
        self.assertTrue(any(event=='screen_resume' for event,_ in self.execute()))

    def test_owned_shimen_puzzle_reaches_collection_without_navigation(self):
        self.lua.execute('''
            config.step='advance';config.task='shimen';config.verify_role=true
            package.preload['common.navigation']=function() return {prepare_recorded=function()
                error('must not navigate away from puzzle evidence') end} end
            package.preload['tasks.shimen.pages']=function() return {state=function() return 'puzzle' end} end
            package.preload['progress']=function() return {read=function() return {status='running'} end} end
        ''')
        events=self.execute()
        self.assertTrue(any(event=='screen_resume' for event,_ in events))
        self.assertFalse(any(event=='failed' for event,_ in events))

    def test_shimen_sampling_keeps_verified_retry_page_for_own_collector(self):
        self.lua.execute('''
            config.step='browse';config.task='shimen';config.verify_role=true
            package.preload['common.navigation']=function() return {prepare_recorded=function()
                error('must not navigate away from Shimen free retry') end} end
            package.preload['tasks.shimen.pages']=function() return {state=function() return 'retry' end} end
        ''')
        events=self.execute()
        self.assertTrue(any(event=='screen_resume' for event,_ in events))
        self.assertFalse(any(event=='failed' for event,_ in events))

    def test_shimen_idle_pages_verify_identity_before_task_execution(self):
        for state in ('ready', 'completed_card'):
            with self.subTest(state=state):
                self.setUp()
                self.lua.globals().idle_state=state
                self.lua.execute('''
                    config.step='complete';config.task='shimen';config.verify_role=true
                    package.preload['tasks.shimen.pages']=function() return {state=function() return idle_state end} end
                    package.preload['common.navigation']=function() return {prepare_recorded=function(ctx)
                        ctx.identity_verified=true;return true end} end
                    package.preload['tasks.shimen.task']=function() return {run=function(ctx)
                        assert(ctx.identity_verified,'idle page must verify home identity first')
                        return {status='done',reason='verified'} end} end
                ''')
                events=self.execute()
                self.assertIn(('task_result', 'shimen status=done reason=verified'), events)
                self.assertFalse(any(event in ('failed','screen_resume') for event,_ in events))


if __name__ == '__main__':
    unittest.main()
