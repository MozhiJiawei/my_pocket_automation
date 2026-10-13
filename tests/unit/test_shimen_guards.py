"""Exercise task ownership, bounded retries and completion through real Lua."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class ShimenGuardTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            state='find'; saved={status='running',attempts=1,completed_count=0,reserved_energy=2}
            captures={}; solves=0; taps=0
            ctx={config={step='advance'},identity_verified=true}
            package.preload['tasks.shimen.pages']=function() return {
                features={back='back',accept='accept'},
                actions={retry='retry',dialogue='dialogue'},state=function() return state end,
                count=function() return count end} end
            package.preload['common.device']=function() return {
                tap=function() taps=taps+1;return true end,
                wait=function(predicate) return predicate() end} end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                table.insert(captures,label) end} end
            package.preload['progress']=function() return {
                read=function() return saved end,
                write=function(c,task,status,stage,record)
                    saved=record;saved.status=status;saved.stage=stage
                end} end
            package.preload['tasks.shimen.find']=function() return {solve=function()
                assert(saved.find_attempts>0 and saved.stage=='find_attempt_reserved')
                solves=solves+1
                return success==true,'find_icon_not_found'
            end} end
            package.preload['tasks.shimen.puzzle']=function() return {solve=function(c,family)
                puzzle_family=family;return false,'puzzle_family_unrecognized'
            end} end
            mSleep=function() end
        ''')
        self.task=self.lua.eval("require('tasks.shimen.task')")[0]

    def run_task(self):
        return self.task.run(self.lua.globals().ctx)

    def test_first_attempt_and_three_retries_survive_repeated_invocations(self):
        for number in range(1,5):
            result=self.run_task()
            self.assertEqual(self.lua.globals().saved.find_attempts,number)
        self.assertEqual(result['reason'],'find_retry_limit_reached')
        self.assertEqual(result['status'],'blocked')
        self.run_task()
        self.assertEqual(self.lua.globals().solves,4)

    def test_missing_ownership_does_not_solve(self):
        self.lua.execute('saved=nil')
        self.assertEqual(self.run_task()['status'],'blocked')
        self.assertEqual(self.lua.globals().solves,0)

    def test_successful_minigame_does_not_complete_task(self):
        self.lua.execute('success=true')
        self.assertEqual(self.run_task()['reason'],'one_minigame_completed')
        self.assertEqual(self.lua.globals().saved.completed_count,0)
        self.assertEqual(self.lua.globals().saved.status,'running')

    def test_puzzle_attempts_old_features_and_stops_on_unrecognized_family(self):
        self.lua.execute("state='puzzle'")
        self.assertEqual(self.run_task()['reason'],'puzzle_family_unrecognized')
        self.assertEqual(self.lua.globals().puzzle_family,'auto')
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().solves,0)

    def test_explicit_puzzle_run_cannot_operate_a_find_page(self):
        self.lua.execute("ctx.config.shimen_puzzle_family='老虎'")
        self.assertEqual(self.run_task()['reason'],'shimen_puzzle_page_not_verified')
        self.assertEqual(self.lua.globals().solves,0)

    def test_idle_requires_matching_count_and_identity(self):
        self.lua.execute("state='idle';count=2")
        self.assertEqual(self.run_task()['status'],'blocked')
        self.lua.execute('count=1;ctx.identity_verified=false')
        self.assertEqual(self.run_task()['status'],'blocked')
        self.lua.execute('ctx.identity_verified=true')
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().saved.completed_count,1)

    def test_unknown_page_does_not_tap(self):
        self.lua.execute("state='unknown'")
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        self.assertEqual(self.lua.globals().taps,0)

    def test_unchanged_dialogue_stops_after_one_action(self):
        self.lua.execute("state='dialogue'")
        self.assertEqual(self.run_task()['reason'],'shimen_action_postcondition_not_verified')
        self.assertEqual(self.lua.globals().taps,1)

    def test_ready_completes_only_verified_owned_count(self):
        self.lua.execute("state='ready';count=1")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().saved.completed_count,1)
        self.assertEqual(self.lua.globals().taps,0)

    def test_ready_count_mismatch_cannot_accept(self):
        self.lua.execute("state='ready';count=2;ctx.config.step='complete'")
        self.assertEqual(self.run_task()['reason'],'shimen_completion_count_mismatch')
        self.assertEqual(self.lua.globals().taps,0)

    def test_accept_reserves_next_task_and_resets_only_its_find_attempts(self):
        self.lua.execute("state='ready';count=1;ctx.config.step='complete';saved.find_attempts=4")
        self.assertEqual(self.run_task()['reason'],'shimen_accept_postcondition_not_verified')
        self.assertEqual(self.lua.globals().saved.completed_count,1)
        self.assertEqual(self.lua.globals().saved.attempts,2)
        self.assertEqual(self.lua.globals().saved.find_attempts,0)
        self.assertEqual(self.lua.globals().saved.reserved_energy,4)
        self.assertEqual(self.lua.globals().taps,1)

    def test_twentieth_delivery_completes_without_accepting_more(self):
        self.lua.execute("state='ready';count=20;saved.attempts=20;saved.completed_count=19;ctx.config.step='complete'")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().saved.completed_count,20)
        self.assertEqual(self.lua.globals().saved.status,'done')
        self.assertEqual(self.lua.globals().taps,0)

    def test_unverified_role_must_leave_ready_before_new_accept(self):
        self.lua.execute("state='ready';count=1;ctx.identity_verified=false;ctx.config.step='complete'")
        self.assertEqual(self.run_task()['reason'],'shimen_return_postcondition_not_verified')
        self.assertEqual(self.lua.globals().saved.completed_count,0)
        self.assertEqual(self.lua.globals().saved.attempts,1)

    def test_complete_continues_after_puzzle_but_never_records_delivery(self):
        self.lua.execute("""
            state='puzzle';ctx.config.step='complete'
            package.preload['tasks.shimen.puzzle']=function() return {solve=function()
                state='unknown';return true,'puzzle_solved'
            end} end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        self.assertEqual(self.lua.globals().saved.completed_count,0)
        self.assertEqual(self.lua.globals().saved.stage,'puzzle_exit_requires_delivery_verification')
