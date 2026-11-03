"""Raw Lua outcomes and acceptance evidence survive secondary diagnostic failures."""
from pathlib import Path
import tempfile
import unittest

from lupa import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
    return lua


class PuzzleFailureEvidenceTest(unittest.TestCase):
    def task_runtime(self, task):
        lua = runtime()
        lua.globals().task_name = task
        lua.execute('''
            state='puzzle'; clock=0; solves=0; taps=0
            os.time=function() return clock end
            mSleep=function(ms) clock=clock+ms/1000 end
            ctx={config={step='complete',allow_reward_claim=false},identity_verified=true}
            record={status='running',attempts=1}
            package.preload['tasks.'..task_name..'.pages']=function() return {
                state=function() return state end,
                features={puzzle={retry_button='puzzle_retry'}},actions={puzzle_retry='puzzle_retry'}
            } end
            package.preload['common.device']=function() return {
                wait=function(predicate) return predicate() end,
                tap=function() taps=taps+1;return false end
            } end
            package.preload['common.navigation']=function() return {} end
            package.preload['common.list_navigation']=function() return {} end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function() return 'failure.png' end} end
            package.preload['dfx.materials']=function() return {
                prepare=function() return not prepare_failed,'materials_puzzle_not_verified' end,
                keep=function() end,clear=function() end
            } end
            package.preload['progress']=function() return {
                read=function() return record end,
                write=function(c,name,status,stage,value)
                    record=value or record;record.status=status;record.stage=stage
                end
            } end
            package.preload['tasks.'..task_name..'.puzzle']=function() return {
                solve=function()
                    solves=solves+1
                    if solve_error then error('communication_failed') end
                    if solve_success then state='puzzle_retry';return true,'solved' end
                    return false,'puzzle_tiles_unrecognized'
                end
            } end
        ''')
        return lua

    def run_task(self, lua, task):
        return lua.eval(f"require('tasks.{task}.task').run(ctx)")

    def test_puzzle_solver_failure_keeps_original_reason(self):
        for task in ('shimen', 'zhuagui'):
            with self.subTest(task=task):
                lua = self.task_runtime(task)
                result = self.run_task(lua, task)
                self.assertEqual(result['status'], 'paused')
                self.assertEqual(result['reason'], 'puzzle_tiles_unrecognized')
                self.assertEqual(lua.globals().solves, 1)

    def test_puzzle_diagnostic_failures_preserve_outcome_and_try_both_channels(self):
        cases = (
            ('shimen', '', 'puzzle_tiles_unrecognized'),
            ('zhuagui', '', 'puzzle_tiles_unrecognized'),
            ('shimen', 'solve_success=true', 'puzzle_game_result_not_verified'),
            ('zhuagui', "state='puzzle_retry';record.puzzle_retries=1", 'puzzle_retry_not_authorized'),
        )
        for task, setup, reason in cases:
            for failed_channel in ('materials', 'snapshot', 'both'):
                with self.subTest(task=task, reason=reason, failed_channel=failed_channel):
                    lua = self.task_runtime(task)
                    lua.globals().failed_channel = failed_channel
                    lua.execute(setup)
                    lua.execute('''
                        keeps=0;captures=0
                        require('dfx.materials').keep=function()
                            keeps=keeps+1
                            if failed_channel~='snapshot' then error('materials_failed') end
                        end
                        require('dfx.snapshot').capture=function()
                            captures=captures+1
                            if failed_channel~='materials' then error('snapshot_failed') end
                            return 'failure.png'
                        end
                    ''')
                    result = self.run_task(lua, task)
                    self.assertEqual(result['status'], 'paused')
                    self.assertEqual(result['reason'], reason)
                    self.assertEqual(result['failure_evidence'],
                                     'failure.png' if failed_channel == 'materials' else None)
                    self.assertEqual(lua.globals().keeps, 1)
                    self.assertEqual(lua.globals().captures, 1)
                    self.assertEqual(lua.globals().taps, 0)

    def test_daily_keeps_task_reason_when_task_and_secondary_capture_both_fail(self):
        for task in ('shimen', 'zhuagui'):
            with self.subTest(task=task):
                lua = self.task_runtime(task)
                lua.execute('''
                    events={};captures=0
                    config=ctx.config
                    config.mode='run';config.step='daily';config.tasks={task_name}
                    config.accounts={{alias='first'}}
                    ctx.run_id='fake'
                    loadfile=function() return function() return config end end
                    nLog=function() end
                    appIsRunning=function() return 1 end
                    package.preload['TSLib']=function() return {} end
                    package.preload['common.screen']=function() return {init=function() end} end
                    package.preload['dfx.run']=function() return {new=function() return ctx end} end
                    package.preload['dfx.profile']=function() return {install=function() end,flush=function() end} end
                    package.preload['dfx.log']=function() return {write=function(c,event,detail)
                        events[#events+1]={event,detail}
                    end} end
                    package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                        if label=='start' then return end
                        captures=captures+1;error('snapshot_failed')
                    end} end
                    package.preload['completion']=function() return {read=function() end} end
                    package.preload['common.navigation']=function() return {
                        verify_roster=function() return true end,
                        prepare_recorded=function(c) c.identity_verified=true;return true end
                    } end
                ''')
                lua.execute((ROOT / 'src/main.lua').read_text(encoding='utf-8'))
                events = [(item[1], item[2]) for item in lua.globals().events.values()]
                result = ('task_result', f'{task} status=paused reason=puzzle_tiles_unrecognized')
                self.assertIn(result, events)
                self.assertIn(('summary', f'all_roles_done=false selected_done=false daily_done=false reason={task}_paused'), events)
                self.assertIn(('finished', 'script_exited_normally'), events)
                self.assertFalse(any(event == 'home_verified' for event, _ in events))
                self.assertEqual(lua.globals().captures, 2)

    def test_materials_precondition_failure_keeps_its_own_reason(self):
        for task in ('shimen', 'zhuagui'):
            with self.subTest(task=task):
                lua = self.task_runtime(task)
                lua.execute('prepare_failed=true')
                result = self.run_task(lua, task)
                self.assertEqual(result['reason'], 'materials_puzzle_not_verified')
                self.assertEqual(lua.globals().solves, 0)

    def test_solver_exception_is_not_converted_into_a_puzzle_outcome(self):
        for task in ('shimen', 'zhuagui'):
            with self.subTest(task=task):
                lua = self.task_runtime(task)
                lua.execute('solve_error=true')
                ok, error = lua.eval(f"pcall(require('tasks.{task}.task').run,ctx)")
                self.assertFalse(ok)
                self.assertIn('communication_failed', error)

    def test_shimen_debug_precondition_failure_does_not_attempt_puzzle(self):
        lua = self.task_runtime('shimen')
        lua.execute("state='puzzle_retry';ctx.config.shimen_puzzle_family='example'")
        result = self.run_task(lua, 'shimen')
        self.assertEqual(result['reason'], 'shimen_puzzle_page_not_verified')
        self.assertEqual(lua.globals().solves, 0)

    def test_shimen_retry_after_an_attempt_is_a_puzzle_failure(self):
        lua = self.task_runtime('shimen')
        lua.execute('solve_success=true')
        result = self.run_task(lua, 'shimen')
        self.assertEqual(result['reason'], 'puzzle_game_result_not_verified')
        self.assertEqual(lua.globals().taps, 0)

    def test_shimen_unattempted_retry_keeps_action_failure_reason(self):
        lua = self.task_runtime('shimen')
        lua.execute("state='puzzle_retry'")
        result = self.run_task(lua, 'shimen')
        self.assertEqual(result['reason'], 'shimen_action_postcondition_not_verified')

    def test_zhuagui_exhausted_puzzle_retry_keeps_reason_and_sends_no_tap(self):
        lua = self.task_runtime('zhuagui')
        lua.execute("state='puzzle_retry';record.puzzle_retries=1")
        result = self.run_task(lua, 'zhuagui')
        self.assertEqual(result['reason'], 'puzzle_retry_not_authorized')
        self.assertEqual(lua.globals().taps, 0)

    def test_zhuagui_retry_target_change_keeps_action_failure_reason(self):
        lua = self.task_runtime('zhuagui')
        lua.execute("state='puzzle_retry'")
        result = self.run_task(lua, 'zhuagui')
        self.assertEqual(result['reason'], 'puzzle_retry_target_changed')
        self.assertEqual(lua.globals().taps, 1)


class DailyAcceptanceEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.lua = runtime()
        self.lua.execute('''
            events={}; home=true; ready=true
            config={mode='run',step='daily',tasks={'shimen'},allow_reward_claim=false,accounts={{alias='first'}}}
            ctx={config=config,run_id='fake'}
            outcome={status='done',reason='completion_card_verified'}
            loadfile=function() return function() return config end end
            nLog=function() end
            appIsRunning=function() return 1 end
            package.preload['TSLib']=function() return {} end
            package.preload['common.screen']=function() return {init=function()
                if init_error then error('screen_init_failed') end
            end} end
            package.preload['dfx.run']=function() return {new=function() return ctx end} end
            package.preload['dfx.profile']=function() return {install=function() end,flush=function() end} end
            package.preload['dfx.log']=function() return {write=function(c,event,detail)
                events[#events+1]={event,detail}
            end} end
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                events[#events+1]={'capture',label}
                if capture_error and label~='start' then error('capture_failed') end
            end} end
            package.preload['completion']=function() return {read=function() return cached end} end
            package.preload['common.navigation']=function() return {
                verify_roster=function() return true end,
                prepare_recorded=function(c) c.identity_verified=ready;return ready end,
                finish_account=function()
                    events[#events+1]={'home_check',tostring(home)};return home
                end
            } end
            for _,name in ipairs({'shimen','zhuagui','dungeon','rewards'}) do
                package.preload['tasks.'..name..'.task']=function() return {run=function()
                    if task_error then error('communication_failed') end
                    return outcome
                end} end
            end
        ''')

    def events(self):
        return [(item[1], item[2]) for item in self.lua.globals().events.values()]

    def run_daily(self):
        self.lua.execute("require('daily').run(ctx)")
        return self.events()

    def run_main(self):
        self.lua.execute((ROOT / 'src/main.lua').read_text(encoding='utf-8'))
        return self.events()

    def test_daily_task_failure_is_logged_before_failed_secondary_capture(self):
        self.lua.execute("outcome={status='paused',reason='puzzle_tiles_unrecognized'};capture_error=true")
        events = self.run_daily()
        result = ('task_result', 'shimen status=paused reason=puzzle_tiles_unrecognized')
        self.assertLess(events.index(result), events.index(('capture', 'task_shimen_incomplete')))
        self.assertIn(('summary', 'all_roles_done=false selected_done=false daily_done=false reason=shimen_paused'), events)
        self.assertFalse(any(event == 'home_verified' for event, _ in events))

    def test_generic_failure_keeps_its_original_reason(self):
        self.lua.execute("outcome={status='paused',reason='shimen_puzzle_page_not_verified'}")
        events = self.run_daily()
        self.assertIn(('task_result', 'shimen status=paused reason=shimen_puzzle_page_not_verified'), events)

    def test_task_done_and_verified_home_emit_acceptance(self):
        events = self.run_daily()
        boundary = ('home_verified', 'account=first task=shimen')
        self.assertLess(events.index(('home_check', 'true')), events.index(boundary))

    def test_cached_completion_still_requires_verified_home(self):
        self.lua.execute('cached=true;task_error=true')
        events = self.run_daily()
        self.assertIn(('task_result', 'shimen status=done reason=daily_completion_ledger_verified'), events)
        self.assertIn(('home_verified', 'account=first task=shimen'), events)

    def test_home_failure_keeps_navigation_result_and_stops_account(self):
        self.lua.execute('home=false')
        events = self.run_daily()
        result = ('task_result', 'navigation status=blocked reason=return_home_not_verified')
        self.assertIn(result, events)
        self.assertFalse(any(event in ('home_verified', 'account_result') for event, _ in events))

    def test_identity_prepare_failure_keeps_account_result(self):
        self.lua.execute('ready=false')
        events = self.run_daily()
        self.assertIn(('task_result', 'account status=blocked reason=saved_role_not_ready'), events)
        self.assertFalse(any(event == 'home_verified' for event, _ in events))

    def test_identity_evidence_failure_does_not_hide_account_reason(self):
        self.lua.execute('ready=false;capture_error=true')
        events = self.run_daily()
        result = ('task_result', 'account status=blocked reason=saved_role_not_ready')
        self.assertLess(events.index(result), events.index(('capture', 'role_identity_not_verified')))
        self.assertIn(('summary', 'all_roles_done=false selected_done=false daily_done=false reason=saved_role_not_ready'), events)

    def test_home_evidence_failure_does_not_hide_navigation_reason(self):
        self.lua.execute('home=false;capture_error=true')
        events = self.run_daily()
        self.assertIn(('task_result', 'navigation status=blocked reason=return_home_not_verified'), events)
        self.assertIn(('summary', 'all_roles_done=false selected_done=false daily_done=false reason=return_home_not_verified'), events)
        self.assertFalse(any(event == 'home_verified' for event, _ in events))

    def test_main_single_task_preserves_puzzle_failure_reason(self):
        self.lua.execute("config.tasks=nil;config.step='complete';config.task='shimen';outcome={status='paused',reason='puzzle_tiles_unrecognized'}")
        events = self.run_main()
        self.assertIn(('task_result', 'shimen status=paused reason=puzzle_tiles_unrecognized'), events)
        self.assertFalse(any(event == 'home_verified' for event, _ in events))

    def test_main_prepare_failure_keeps_account_result(self):
        self.lua.execute('config.tasks=nil;ready=false')
        events = self.run_main()
        self.assertIn(('task_result', 'account status=blocked reason=saved_role_not_ready'), events)
        self.assertFalse(any(event == 'home_verified' for event, _ in events))

    def test_main_exception_keeps_original_failure(self):
        self.lua.execute("config.tasks=nil;config.step='complete';config.task='shimen';task_error=true")
        events = self.run_main()
        self.assertTrue(any(event == 'failed' and 'communication_failed' in detail for event, detail in events))
        self.assertFalse(any(event == 'home_verified' for event, _ in events))

    def test_main_legacy_daily_home_boundary_uses_last_completed_task(self):
        self.lua.execute('config.tasks=nil')
        events = self.run_main()
        self.assertIn(('home_verified', 'account=first task=rewards'), events)
        self.assertEqual(sum(event == 'home_verified' for event, _ in events), 1)

    def test_main_legacy_daily_home_failure_identifies_last_task(self):
        self.lua.execute('config.tasks=nil;home=false')
        events = self.run_main()
        self.assertIn(('task_result', 'navigation status=blocked reason=return_home_not_verified'), events)
        self.assertFalse(any(event == 'home_verified' for event, _ in events))

    def test_main_cannot_credit_a_placeholder_as_a_completed_home_boundary(self):
        self.lua.execute("config.tasks=nil;outcome.status='not_implemented'")
        events = self.run_main()
        self.assertIn(('home_check', 'true'), events)
        self.assertFalse(any(event == 'home_verified' for event, _ in events))

    def test_main_early_error_emits_no_verified_boundary(self):
        self.lua.execute('init_error=true')
        events = self.run_main()
        self.assertTrue(any(event == 'failed' and 'screen_init_failed' in detail for event, detail in events))
        self.assertFalse(any(event == 'home_verified' for event, _ in events))


class AcceptanceLogDefaultsTest(unittest.TestCase):
    def test_acceptance_events_are_info_without_verbose_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            lua = runtime()
            lua.globals().folder = Path(folder).as_posix()
            lua.execute('''
                nLog=function() end
                local ctx={config={},run_id='fake',log_path=folder..'/main.log'}
                local log=require('dfx.log')
                log.write(ctx,'task_result','shimen status=paused reason=puzzle_tiles_unrecognized')
                log.write(ctx,'account_verified','account=first')
                log.write(ctx,'home_verified','account=first task=shimen')
                log.write(ctx,'state','debug noise')
            ''')
            lines = (Path(folder) / 'main.log').read_text(encoding='utf-8').splitlines()
            self.assertEqual(lines, [
                '[daily][fake][task_result] shimen status=paused reason=puzzle_tiles_unrecognized',
                '[daily][fake][account_verified] account=first',
                '[daily][fake][home_verified] account=first task=shimen',
            ])


if __name__ == '__main__':
    unittest.main()
