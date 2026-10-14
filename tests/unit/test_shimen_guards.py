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
                read=function(c,task,date) return date and previous or saved end,
                write=function(c,task,status,stage,record,date)
                    if date then previous=record;previous.status=status;previous.stage=stage
                    else saved=record;saved.status=status;saved.stage=stage end
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

    def test_unknown_transition_waits_for_verified_page(self):
        self.lua.execute("""
            state='unknown';count=1
            package.loaded['common.device'].wait=function(predicate,attempts,interval)
                wait_attempts=attempts;wait_interval=interval
                state='ready';return predicate()
            end
        """)
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().wait_attempts,10)
        self.assertEqual(self.lua.globals().wait_interval,500)
        self.assertEqual(self.lua.globals().saved.completed_count,1)
        self.assertEqual(self.lua.globals().taps,0)

    def test_persistent_unknown_page_stops_after_bounded_observation(self):
        self.lua.execute("""
            state='unknown'
            package.loaded['common.device'].wait=function(predicate,attempts,interval)
                wait_attempts=attempts;wait_interval=interval
                return predicate()
            end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        self.assertEqual(self.lua.globals().wait_attempts,10)
        self.assertEqual(self.lua.globals().wait_interval,500)
        self.assertEqual(self.lua.globals().saved.completed_count,0)
        self.assertEqual(self.lua.globals().taps,0)

    def test_final_list_search_never_completes_from_missing_entry(self):
        self.lua.execute("""
            state='task_list';ctx.config.step='complete'
            saved.attempts=20;saved.completed_count=19;saved.reserved_energy=40
            package.loaded['common.detector']={present=function() return false end}
            swipes=0
            package.loaded['common.device'].swipe=function()
                swipes=swipes+1;return true
            end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_completed_card_not_found')
        self.assertEqual(self.lua.globals().swipes,4)
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().saved.completed_count,19)
        self.assertEqual(self.lua.globals().saved.status,'running')

    def test_completed_card_verifies_the_twentieth_delivery_without_new_actions(self):
        self.lua.execute("state='completed_card';saved.attempts=20;saved.completed_count=19")
        self.assertEqual(self.run_task()['reason'],'all_twenty_tasks_completed')
        self.assertEqual(self.lua.globals().saved.status,'done')
        self.assertEqual(self.lua.globals().saved.completed_count,20)
        self.assertEqual(self.lua.globals().taps,0)

    def test_completed_card_cannot_complete_an_earlier_owned_attempt(self):
        self.lua.execute("state='completed_card';saved.attempts=19;saved.completed_count=18")
        self.assertEqual(self.run_task()['reason'],'shimen_completed_card_ledger_mismatch')
        self.assertEqual(self.lua.globals().saved.completed_count,18)
        self.assertEqual(self.lua.globals().taps,0)

    def test_completed_card_requires_reobservation_after_identity_verification(self):
        self.lua.execute("""
            state='completed_card';saved.attempts=20;saved.completed_count=19
            ctx.identity_verified=false
            package.preload['common.navigation']=function() return {
                prepare_recorded=function(c)
                    c.identity_verified=true;state='unknown';return true
                end} end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        self.assertEqual(self.lua.globals().saved.status,'running')
        self.assertEqual(self.lua.globals().saved.completed_count,19)
        self.assertEqual(self.lua.globals().taps,0)

    def test_first_attempt_and_three_retries_survive_repeated_invocations(self):
        for number in range(1,5):
            result=self.run_task()
            self.assertEqual(self.lua.globals().saved.find_attempts,number)
        self.assertEqual(result['reason'],'find_retry_limit_reached')
        self.assertEqual(result['status'],'blocked')
        self.run_task()
        self.assertEqual(self.lua.globals().solves,4)

    def test_find_preparation_cannot_open_a_fifth_opportunity(self):
        self.lua.execute("""
            state='prepare_find';saved.find_attempts=4
            package.loaded['tasks.shimen.pages'].actions.prepare_find='prepare_find'
        """)
        self.assertEqual(self.run_task()['reason'],'find_retry_limit_reached')
        self.assertEqual(self.lua.globals().taps,0)

    def test_find_preparation_can_use_the_last_allowed_retry(self):
        self.lua.execute("""
            state='prepare_find';saved.find_attempts=3
            package.loaded['tasks.shimen.pages'].actions.prepare_find='prepare_find'
            package.loaded['common.device'].tap=function() taps=taps+1;state='find';return true end
        """)
        self.assertEqual(self.run_task()['reason'],'find_retry_limit_reached')
        self.assertEqual(self.lua.globals().saved.find_attempts,4)
        self.assertEqual(self.lua.globals().taps,1)
        self.assertEqual(self.lua.globals().solves,1)

    def test_missing_ownership_does_not_solve(self):
        self.lua.execute('saved=nil')
        self.assertEqual(self.run_task()['status'],'blocked')
        self.assertEqual(self.lua.globals().solves,0)

    def test_entry_inspects_existing_card_without_ownership_or_new_accept(self):
        self.lua.execute("saved=nil;state='ready';count=0;ctx.config.step='enter'")
        self.assertEqual(self.run_task()['status'],'running')
        self.assertEqual(self.lua.globals().taps,0)
        self.assertIsNone(self.lua.globals().saved)
        self.assertEqual(self.lua.globals().solves,0)

    def test_entry_requires_verified_identity(self):
        self.lua.execute("saved=nil;state='ready';ctx.identity_verified=false;ctx.config.step='enter'")
        self.assertEqual(self.run_task()['reason'],'role_identity_not_verified')
        self.assertEqual(self.lua.globals().taps,0)

    def test_entry_opens_task_list_and_card_without_writing_progress(self):
        self.lua.execute("""
            saved=nil;state='home';ctx.config.step='enter';count=0
            package.loaded['common.device'].tap=function(c,feature,label)
                taps=taps+1
                if label=='shimen_open_tasks' then state='task_list'
                elseif label=='shimen_open_card' then state='ready' end
                return true
            end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_task_entry_verified')
        self.assertEqual(self.lua.globals().taps,2)
        self.assertIsNone(self.lua.globals().saved)

    def test_entry_can_reopen_carried_task_directly_from_home(self):
        self.lua.execute("""
            saved=nil;state='home';ctx.config.step='enter';count=0
            package.loaded['common.device'].tap=function()
                taps=taps+1;state='go';return true
            end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_task_entry_verified')
        self.assertEqual(self.lua.globals().taps,1)
        self.assertIsNone(self.lua.globals().saved)

    def carryover(self,find_attempts=0):
        self.lua.execute(f"""
            saved=nil;count=0;state='dialogue';ctx.config.step='complete'
            ctx.config.business_date='20261014';ctx.config.shimen_resume_date='20261013'
            previous={{status='running',attempts=6,completed_count=5,reserved_energy=12,find_attempts={find_attempts}}}
        """)

    def test_carryover_does_not_copy_prior_day_completed_count_or_energy(self):
        self.carryover(2)
        self.assertEqual(self.run_task()['reason'],'shimen_action_postcondition_not_verified')
        saved=self.lua.globals().saved
        self.assertEqual(saved.attempts,0)
        self.assertEqual(saved.completed_count,0)
        self.assertEqual(saved.reserved_energy,0)
        self.assertEqual(saved.find_attempts,2)
        self.assertEqual(saved.carryover_pending,1)
        self.assertEqual(saved.carryover_source_attempt,6)
        self.assertEqual(self.lua.globals().previous.completed_count,5)

    def test_carryover_requires_old_ownership_zero_count_and_earlier_date(self):
        for change in ('previous=nil','count=1',"previous.status='done'",'previous.attempts=0',
                       "ctx.config.shimen_resume_date='20261015'","state='ready'"):
            with self.subTest(change=change):
                self.carryover()
                self.lua.execute(change)
                self.assertEqual(self.run_task()['reason'],'shimen_carryover_not_verified')
                self.assertIsNone(self.lua.globals().saved)

    def test_carryover_cannot_reset_exhausted_find_attempts(self):
        self.carryover(4)
        self.lua.execute("state='find'")
        self.assertEqual(self.run_task()['reason'],'find_retry_limit_reached')
        self.assertEqual(self.lua.globals().solves,0)

    def test_carried_delivery_keeps_today_zero_then_accepts_first_new_task(self):
        self.carryover(3)
        self.lua.execute("""
            state='ready';saved={status='running',attempts=0,completed_count=0,reserved_energy=0,
                find_attempts=3,carryover_pending=1,carryover_source_date=20261013,carryover_source_attempt=6}
            package.loaded['common.device'].tap=function(c,feature)
                assert(feature=='accept');taps=taps+1;count=1;state='unknown';return true
            end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        saved=self.lua.globals().saved
        self.assertEqual(saved.carryover_pending,0)
        self.assertEqual(saved.completed_count,0)
        self.assertEqual(saved.attempts,1)
        self.assertEqual(saved.reserved_energy,2)
        self.assertEqual(saved.find_attempts,0)
        self.assertEqual(self.lua.globals().taps,1)
        self.assertEqual(self.lua.globals().previous.status,'carried_over')
        self.assertEqual(self.lua.globals().previous.completed_count,5)

    def test_completed_carryover_retires_old_owner_after_restart(self):
        self.carryover()
        self.lua.execute("""
            state='unknown';saved={status='running',attempts=5,completed_count=4,
                carryover_pending=0,carryover_source_date=20261013,carryover_source_attempt=6}
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        self.assertEqual(self.lua.globals().previous.status,'carried_over')
        self.assertEqual(self.lua.globals().previous.completed_count,5)
        self.assertEqual(self.lua.globals().saved.attempts,5)
        self.assertEqual(self.lua.globals().saved.completed_count,4)

    def test_carryover_cannot_retire_a_different_old_attempt(self):
        self.carryover()
        self.lua.execute("""
            state='unknown';previous.attempts=7
            saved={status='running',attempts=5,completed_count=4,
                carryover_pending=0,carryover_source_date=20261013,carryover_source_attempt=6}
        """)
        self.run_task()
        self.assertEqual(self.lua.globals().previous.status,'running')

    def test_carried_delivery_cannot_accept_before_identity_verification(self):
        self.carryover()
        self.lua.execute("""
            state='ready';ctx.identity_verified=false
            saved={status='running',attempts=0,completed_count=0,carryover_pending=1}
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_return_postcondition_not_verified')
        self.assertEqual(self.lua.globals().saved.attempts,0)

    def test_first_new_day_task_requires_verified_zero_idle_count(self):
        self.lua.execute("saved=nil;state='ready';count=0;ctx.config.step='complete'")
        self.assertEqual(self.run_task()['reason'],'shimen_accept_postcondition_not_verified')
        self.assertEqual(self.lua.globals().saved.attempts,1)
        self.assertEqual(self.lua.globals().saved.completed_count,0)
        self.assertEqual(self.lua.globals().saved.reserved_energy,2)

    def test_zero_ledger_cannot_adopt_unrecorded_active_task(self):
        self.lua.execute("saved=nil;state='find';count=0;ctx.config.step='complete'")
        self.assertEqual(self.run_task()['reason'],'shimen_active_task_ownership_missing')
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

    def test_battle_loading_waits_without_actions_or_completion(self):
        self.lua.execute("state='loading';mSleep=function() state='unknown' end")
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().saved.completed_count,0)

    def test_gourd_notice_waits_and_never_opens_the_gourd(self):
        self.lua.execute("state='gourd_notice'")
        self.assertEqual(self.run_task()['reason'],'shimen_gourd_notice_not_closed')
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().saved.completed_count,0)

    def test_auto_closed_gourd_notice_reobserves_delivery(self):
        self.lua.execute("""
            state='gourd_notice';count=1
            package.loaded['common.device'].wait=function() state='ready';return true end
        """)
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().saved.completed_count,1)

    def test_unchanged_dialogue_stops_after_one_action(self):
        self.lua.execute("state='dialogue'")
        self.assertEqual(self.run_task()['reason'],'shimen_action_postcondition_not_verified')
        self.assertEqual(self.lua.globals().taps,1)

    def test_disappeared_control_reobserves_changed_page_without_blind_tap(self):
        self.lua.execute("""
            state='dialogue'
            package.loaded['common.device'].tap=function()
                state='unknown';return false
            end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().saved.completed_count,0)

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

    def test_action_limit_is_per_owned_task_across_twenty_verified_deliveries(self):
        self.lua.execute("""
            state='ready';count=1;ctx.config.step='complete'
            package.loaded['common.device'].tap=function(c,feature)
                taps=taps+1
                if feature=='accept' then count=count+1;state='dialogue'
                elseif feature=='dialogue' then state='ready' end
                return true
            end
        """)
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().saved.completed_count,20)
        self.assertEqual(self.lua.globals().saved.reserved_energy,40)
        self.assertEqual(self.lua.globals().taps,38)

    def test_action_limit_still_stops_one_task_after_twelve_flow_actions(self):
        self.lua.execute("""
            state='dialogue';ctx.config.step='complete'
            package.loaded['tasks.shimen.pages'].actions.go='go'
            package.loaded['common.device'].tap=function()
                taps=taps+1;state=state=='dialogue' and 'go' or 'dialogue'
                return true
            end
        """)
        self.assertEqual(self.run_task()['reason'],'shimen_action_limit')
        self.assertEqual(self.lua.globals().taps,12)
        self.assertEqual(self.lua.globals().saved.completed_count,0)

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

    def test_puzzle_exit_into_failure_prompt_stops_before_free_retry(self):
        self.lua.execute("""
            state='puzzle';ctx.config.step='complete'
            package.loaded['tasks.shimen.pages'].actions.puzzle_retry='puzzle_retry'
            package.preload['tasks.shimen.puzzle']=function() return {solve=function()
                state='puzzle_retry';return true,'puzzle_solved'
            end} end
        """)
        self.assertEqual(self.run_task()['reason'],'puzzle_game_result_not_verified')
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().saved.completed_count,0)

    def test_puzzle_result_failure_survives_restart(self):
        self.lua.execute("""
            state='puzzle_retry';ctx.config.step='complete'
            saved.stage='puzzle_exit_requires_delivery_verification'
            package.loaded['tasks.shimen.pages'].actions.puzzle_retry='puzzle_retry'
        """)
        self.assertEqual(self.run_task()['reason'],'puzzle_game_result_not_verified')
        self.assertEqual(self.lua.globals().taps,0)

    def test_free_find_retry_requires_recorded_recognition_failure(self):
        self.lua.execute("state='retry';saved.find_attempts=1;saved.find_retry_pending=0")
        self.assertEqual(self.run_task()['reason'],'retry_without_recognition_failure')
        self.assertEqual(self.lua.globals().taps,0)

    def test_free_find_retry_never_exceeds_persisted_budget(self):
        self.lua.execute("state='retry';saved.find_attempts=4;saved.find_retry_pending=1")
        self.assertEqual(self.run_task()['reason'],'find_retry_limit_reached')
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().saved.find_attempts,4)

    def test_free_find_retry_preserves_attempts_before_resuming_find(self):
        self.lua.execute('''
            state='retry';saved.find_attempts=2;saved.find_retry_pending=1;success=true
            package.loaded['common.device'].tap=function(c,feature,label)
                assert(feature=='retry' and label=='shimen_free_find_retry')
                assert(saved.find_attempts==2 and saved.stage=='free_find_retry_reserved')
                assert(saved.find_retry_pending==0)
                taps=taps+1;state='find';return true
            end
        ''')
        self.assertEqual(self.run_task()['reason'],'one_minigame_completed')
        self.assertEqual(self.lua.globals().taps,1)
        self.assertEqual(self.lua.globals().saved.find_attempts,3)
        self.assertEqual(self.lua.globals().saved.completed_count,0)
