"""Exercise page recovery, runtime retry bounds and game completion through real Lua."""
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
            keepScreen=function() end
            getColor=function() return (swipes or 0)*0x001010 end
            ctx={config={step='advance',business_date=os.date('%Y%m%d')},identity_verified=true}
            package.preload['tasks.shimen.pages']=function() return {
                features={back='back',accept='accept',task_list='task_list',task_card='task_card'},
                actions={retry='retry',dialogue='dialogue'},state=function() return state end,
                count=function() return count end} end
            package.preload['common.device']=function() return {
                tap=function() taps=taps+1;return true end,
                wait=function(predicate) return predicate() end} end
            package.preload['common.detector']=function() return {
                present=function(feature) return feature=='task_card' and state=='task_list' end
            } end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                table.insert(captures,label) end} end
            package.preload['progress']=function() return {
                read=function(c,task,date) return date and previous or saved end,
                write=function(c,task,status,stage,record,date)
                    record=record or {}
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
            test_clock=0;os.time=function() return test_clock end
            mSleep=function(ms) test_clock=test_clock+ms/1000 end
        ''')
        self.task=self.lua.eval("require('tasks.shimen.task')")[0]

    def run_task(self):
        return self.task.run(self.lua.globals().ctx)

    def test_story_dialogue_advances_through_changed_text(self):
        self.lua.execute("""
            state='story_dialogue'
            getColor=function() return taps*0x101010 end
            package.loaded['common.device'].tap=function()
                taps=taps+1;if taps==2 then state='ready' end;return true
            end
        """)
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().taps,2)

    def test_story_dialogue_stops_if_text_does_not_change(self):
        self.lua.execute("state='story_dialogue'")
        self.assertEqual(self.run_task()['reason'],'shimen_story_dialogue_not_changed')
        self.assertEqual(self.lua.globals().taps,1)

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
        self.assertEqual(self.lua.globals().saved.stage,'delivery_verified')
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
        self.assertEqual(self.lua.globals().swipes,24)
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().saved.completed_count,19)
        self.assertEqual(self.lua.globals().saved.status,'running')

    def test_completed_card_verifies_completion_without_new_actions(self):
        self.lua.execute("state='completed_card';saved.attempts=20;saved.completed_count=19")
        self.assertEqual(self.run_task()['reason'],'completion_card_verified')
        self.assertEqual(self.lua.globals().saved.status,'done')
        self.assertEqual(self.lua.globals().saved.stage,'completion_card_verified')
        self.assertEqual(self.lua.globals().taps,0)

    def test_completed_card_is_authoritative_regardless_of_old_counts(self):
        self.lua.execute("state='completed_card';saved.attempts=19;saved.completed_count=18")
        self.assertEqual(self.run_task()['reason'],'completion_card_verified')
        self.assertEqual(self.lua.globals().saved.status,'done')
        self.assertEqual(self.lua.globals().taps,0)

    def test_unrecorded_completed_card_is_audited_without_inventing_accepts(self):
        self.lua.execute("saved=nil;state='completed_card';ctx.config.step='complete';ctx.config.business_date=os.date('%Y%m%d')")
        self.assertEqual(self.run_task()['reason'],'completion_card_verified')
        self.assertEqual(self.lua.globals().saved.stage,'completion_card_verified')
        self.assertIsNone(self.lua.globals().saved.attempts)
        self.assertIsNone(self.lua.globals().saved.completed_count)
        self.assertIsNone(self.lua.globals().saved.reserved_energy)
        self.assertEqual(self.lua.globals().taps,0)

    def test_unrecorded_completed_card_requires_current_date_and_verified_identity(self):
        for current_date,identity in [(False,True),(True,False)]:
            self.lua.execute("saved=nil;state='completed_card';ctx.config.step='complete';ctx.config.business_date=os.date('%Y%m%d')")
            if not current_date:self.lua.execute("ctx.config.business_date='19000101'")
            self.lua.globals().ctx.identity_verified=identity
            self.assertEqual(self.run_task()['status'],'blocked')
            self.assertIsNone(self.lua.globals().saved)
            self.assertEqual(self.lua.globals().taps,0)

    def test_completed_card_reached_from_home_can_be_audited_without_accepting(self):
        self.lua.execute("""
            saved=nil;state='home';ctx.config.step='complete';ctx.config.business_date=os.date('%Y%m%d')
            package.loaded['common.device'].tap=function(c,feature,label)
                assert(label=='shimen_open_tasks');taps=taps+1;state='completed_card';return true
            end
        """)
        self.assertEqual(self.run_task()['reason'],'completion_card_verified')
        self.assertIsNone(self.lua.globals().saved.attempts)
        self.assertEqual(self.lua.globals().taps,1)

    def test_completion_card_after_new_accept_finishes_without_count_checks(self):
        self.lua.execute("""
            saved=nil;state='ready';count=0;ctx.config.step='complete';ctx.config.business_date=os.date('%Y%m%d')
            package.loaded['common.device'].tap=function(c,feature,label)
                assert(label=='shimen_accept');taps=taps+1;count=1;state='completed_card';return true
            end
        """)
        self.assertEqual(self.run_task()['reason'],'completion_card_verified')
        self.assertEqual(self.lua.globals().saved.status,'done')
        self.assertEqual(self.lua.globals().taps,1)

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

    def test_visible_find_resumes_without_an_old_record(self):
        self.lua.execute('saved=nil')
        self.assertEqual(self.run_task()['reason'],'find_icon_not_found')
        self.assertEqual(self.lua.globals().solves,1)
        self.assertEqual(self.lua.globals().saved.find_attempts,1)

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

    def test_fresh_active_dialogue_has_no_previous_game_state(self):
        self.lua.execute("saved=nil;state='dialogue';ctx.config.step='complete'")
        self.assertEqual(self.run_task()['reason'],'shimen_action_postcondition_not_verified')
        self.assertEqual(self.lua.globals().saved.attempts,0)
        self.assertEqual(self.lua.globals().saved.find_attempts,0)
        self.assertIsNone(self.lua.globals().saved.completed_count)
        self.assertIsNone(self.lua.globals().saved.reserved_energy)

    def test_unrecognized_fresh_page_cannot_create_an_active_task(self):
        for state in ('unknown','idle'):
            self.lua.execute(f"saved=nil;state='{state}';ctx.config.step='complete'")
            self.assertEqual(self.run_task()['reason'],'shimen_task_page_not_verified')
            self.assertIsNone(self.lua.globals().saved)
            self.assertEqual(self.lua.globals().taps,0)

    def test_fresh_run_builds_retry_count_from_zero(self):
        self.lua.execute("saved=nil;state='find';ctx.config.step='complete'")
        self.assertEqual(self.run_task()['reason'],'find_icon_not_found')
        self.assertEqual(self.lua.globals().saved.find_attempts,1)
        self.assertEqual(self.lua.globals().solves,1)

    def test_ready_page_resets_retry_count_before_the_next_task(self):
        self.lua.execute("state='ready';saved={status='running',attempts=0,find_attempts=3};ctx.config.step='complete'")
        self.lua.execute("package.loaded['common.device'].tap=function(c,feature) assert(feature=='accept');taps=taps+1;state='unknown';return true end")
        self.assertEqual(self.run_task()['reason'],'shimen_page_requires_calibration')
        self.assertEqual(self.lua.globals().saved.attempts,1)
        self.assertEqual(self.lua.globals().saved.find_attempts,0)
        self.assertEqual(self.lua.globals().taps,1)

    def test_saved_done_cannot_hide_a_changed_active_page(self):
        self.lua.execute("state='find';saved={status='done',stage='completion_card_verified'}")
        self.assertEqual(self.run_task()['reason'],'find_icon_not_found')
        self.assertEqual(self.lua.globals().saved.status,'running')
        self.assertEqual(self.lua.globals().solves,1)

    def test_saved_done_cannot_hide_an_unknown_page(self):
        self.lua.execute("state='unknown';saved={status='done',stage='completion_card_verified'}")
        self.assertEqual(self.run_task()['reason'],'shimen_task_page_not_verified')
        self.assertEqual(self.lua.globals().taps,0)

    def test_recovered_delivery_cannot_accept_before_identity_verification(self):
        self.lua.execute("state='ready';ctx.identity_verified=false;saved={status='running',attempts=0}")
        self.assertEqual(self.run_task()['reason'],'shimen_return_postcondition_not_verified')
        self.assertEqual(self.lua.globals().saved.attempts,0)

    def test_first_task_uses_idle_page_without_reading_task_numbers(self):
        self.lua.execute("saved=nil;state='ready';ctx.config.step='complete';require('tasks.shimen.pages').count=function() error('task count read') end")
        self.assertEqual(self.run_task()['reason'],'shimen_accept_postcondition_not_verified')
        self.assertEqual(self.lua.globals().saved.attempts,1)
        self.assertIsNone(self.lua.globals().saved.completed_count)
        self.assertIsNone(self.lua.globals().saved.reserved_energy)

    def test_complete_uses_the_visible_active_task(self):
        self.lua.execute("saved=nil;state='find';ctx.config.step='complete'")
        self.assertEqual(self.run_task()['reason'],'find_icon_not_found')
        self.assertEqual(self.lua.globals().solves,1)
        self.assertEqual(self.lua.globals().taps,0)

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

    def test_idle_uses_page_state_and_requires_identity(self):
        self.lua.execute("state='idle';count=2")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.lua.execute("saved.status='running';ctx.identity_verified=false")
        self.assertEqual(self.run_task()['status'],'blocked')
        self.lua.execute("saved.status='running';ctx.identity_verified=true")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().saved.stage,'one_task_completed')

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
        self.assertEqual(self.lua.globals().saved.stage,'delivery_verified')

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

    def test_ready_verifies_delivery_without_finishing_daily_task(self):
        self.lua.execute("state='ready';count=1")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertNotEqual(self.lua.globals().saved.status,'done')
        self.assertEqual(self.lua.globals().taps,0)

    def test_ready_accepts_next_task_without_a_numeric_count_gate(self):
        self.lua.execute("state='ready';count=2;ctx.config.step='complete'")
        self.assertEqual(self.run_task()['reason'],'shimen_accept_postcondition_not_verified')
        self.assertEqual(self.lua.globals().taps,1)

    def test_accept_reserves_next_task_and_resets_only_its_find_attempts(self):
        self.lua.execute("state='ready';count=1;ctx.config.step='complete';saved.find_attempts=4")
        self.assertEqual(self.run_task()['reason'],'shimen_accept_postcondition_not_verified')
        self.assertEqual(self.lua.globals().saved.stage,'accept_reserved')
        self.assertEqual(self.lua.globals().saved.attempts,2)
        self.assertEqual(self.lua.globals().saved.find_attempts,0)
        self.assertEqual(self.lua.globals().saved.reserved_energy,2)
        self.assertEqual(self.lua.globals().taps,1)

    def test_terminal_card_finishes_without_accepting_more(self):
        self.lua.execute("state='completed_card';ctx.config.step='complete';require('tasks.shimen.pages').count=function() error('task count read') end")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().saved.stage,'completion_card_verified')
        self.assertEqual(self.lua.globals().saved.status,'done')
        self.assertEqual(self.lua.globals().taps,0)

    def test_action_limit_is_per_owned_task_across_twenty_verified_deliveries(self):
        self.lua.execute("""
            state='ready';count=1;ctx.config.step='complete'
            package.loaded['common.device'].tap=function(c,feature)
                taps=taps+1
                if feature=='accept' then count=count+1;state='dialogue'
                elseif feature=='dialogue' then state=count>=20 and 'completed_card' or 'ready' end
                return true
            end
        """)
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().saved.stage,'completion_card_verified')
        self.assertIsNone(self.lua.globals().saved.reserved_energy)
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
