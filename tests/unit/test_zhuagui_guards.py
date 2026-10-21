"""Run the actual entry/fee guards with fake pages and device; no paid task."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class ZhuaGuiGuardTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            state='ready_cost_three'; taps={}; record=nil; identity_available=true; fail_reservation=false
            test_clock=0;os.time=function() return test_clock end;mSleep=function(ms) test_clock=test_clock+ms/1000 end
            keepScreen=function() end
            getColor=function() return (entry_scrolls or 0)*0x001010 end
            ctx={config={step='start',allow_reward_claim=false,business_date=os.date('%Y%m%d')},account={alias='fake'}}
            package.preload['tasks.zhuagui.pages']=function() return {
                state=function() return state end,
                features={rules='rules',cancel='cancel',home_tasks='home_tasks',task_card='task_card',accept='accept',task_list_title='task_list_title',depart='depart',go='go',dialogue_next='dialogue_next',retry='retry',quota_dialogue='quota_dialogue',puzzle={retry_button='puzzle_retry'}}
            } end
            package.preload['common.assets.home_tab']=function() return 'home_tab' end
            package.preload['tasks.zhuagui.counter']=function() return {read=function()
                if missing_count then return nil end
                if visible_count~=nil then return visible_count end
                return record and record.attempts or 0
            end} end
            package.preload['dfx.log']=function() return {write=function() end} end
            material_events={}
            package.preload['dfx.materials']=function() return {
                prepare=function(c,task,kind) material_events[#material_events+1]='prepare_'..kind;return true end,
                keep=function(c,reason) material_events[#material_events+1]='keep_'..reason end,
                clear=function() material_events[#material_events+1]='clear' end} end
            package.preload['dfx.snapshot']=function() return {capture=function() end} end
            package.preload['common.detector']=function() return {present=function(feature)
                if feature=='task_card' then
                    return state=='task_list' and (not entry_card_after_scroll or (entry_scrolls or 0)>=entry_card_after_scroll)
                end
                return paid_accept_visible==true and feature=='accept'
            end} end
            package.preload['common.navigation']=function() return {prepare_recorded=function(c)
                assert(state=='home','must return to home for identity verification')
                c.identity_verified=identity_available
                return identity_available
            end} end
            package.preload['progress']=function() return {
                read=function() return record end,
                write=function(c,id,status,stage,counters)
                    if fail_reservation then error('reservation_write_failed') end
                    record={status=status,stage=stage}
                    for _,k in ipairs({'attempts','reserved_energy','completed_count','find_retries','find_retry_pending','puzzle_retries'}) do
                        if counters and counters[k]~=nil then record[k]=counters[k] end
                    end
                end
            } end
            package.preload['common.device']=function() return {
                swipe=function(c,feature,label,start,finish)
                    table.insert(taps,'swipe')
                    entry_scrolls=(entry_scrolls or 0)+1
                    if leave_list_on_scroll then state='unknown' end
                    if completion_card_after_scroll then state='quota_completed_card' end
                    return true
                end,
                wait=function(predicate) return predicate() end,
                tap=function(c,feature,label)
                    if feature=='task_card' and entry_card_after_scroll and
                        (entry_scrolls or 0)<entry_card_after_scroll then return false end
                    table.insert(taps,feature)
                    if feature=='rules' then state='ready_cost_three'
                    elseif feature=='cancel' then state='task_list'
                    elseif feature=='home_tab' then state='home'
                    elseif feature=='home_tasks' then state=home_entry_state or 'task_list'
                    elseif feature=='task_card' then state='ready_cost_three'
                    elseif feature=='retry' then state='find'
                    elseif feature=='puzzle_retry' then state='quota_completed_card'
                    elseif feature=='quota_dialogue' then state='task_list'
                    elseif feature=='accept' then
                        assert(c.identity_verified,'identity required before paid task')
                        assert(record.status=='running' and record.stage=='start_requested','record before accepting')
                        state='active_uncalibrated'
                    end
                    return true
                end
            } end
        ''')
        self.task = self.lua.eval("require('tasks.zhuagui.task')")[0]

    def run_task(self):
        ctx=self.lua.globals().ctx
        if ctx.config.step in ('advance','complete') and ctx.identity_verified is None and not ctx.config.verify_role:
            ctx.identity_verified=True
        return self.task.run(self.lua.globals().ctx)

    def test_unrecorded_terminal_card_finishes_without_numeric_fields(self):
        self.lua.execute("ctx.config.step='complete';ctx.identity_verified=true;state='quota_completed_card'")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().record.stage,'completion_card_verified')
        self.assertIsNone(self.lua.globals().record.attempts)
        self.assert_no_accept()

    def test_incomplete_materials_stop_before_solver_or_paid_retry(self):
        self.lua.execute('''
            ctx.config.step='advance';state='find'
            require('dfx.materials').prepare=function() return false,'catalog_first_frame_not_restored' end
            package.preload['tasks.zhuagui.find']=function() return {solve=function()
                error('must not solve without full originals') end} end
        ''')
        self.assertEqual(self.run_task()['reason'],'catalog_first_frame_not_restored')
        self.assertEqual(len(self.lua.globals().taps),0)

    def assert_no_accept(self):
        self.assertNotIn('accept', list(self.lua.globals().taps.values()))

    def test_default_run_starts_without_a_fee_budget(self):
        result = self.run_task()
        self.assertEqual(result['status'],'running')
        self.assertEqual(self.lua.globals().record.stage,'start_requested')
        self.assertEqual(list(self.lua.globals().taps.values()),['cancel','home_tab','home_tasks','task_card','accept'])

    def test_free_progress_never_taps_when_paid_accept_is_visible(self):
        self.lua.execute("ctx.config.step='advance';state='depart';paid_accept_visible=true;record={status='running',attempts=1,completed_count=0,reserved_energy=3}")
        result=self.run_task()
        self.assertEqual(result['reason'],'free_action_precondition_not_verified')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_free_progress_does_not_read_visible_task_counts(self):
        self.lua.execute("ctx.config.step='advance';state='depart';visible_count=2;record={status='running',attempts=1,completed_count=0,reserved_energy=3}")
        self.lua.execute("require('tasks.zhuagui.counter').read=function() error('task count read') end")
        self.assertEqual(self.run_task()['reason'],'action_limit')
        self.assertEqual(len(self.lua.globals().taps),12)

    def test_free_action_transition_to_paid_ready_is_reobserved_without_a_free_click(self):
        self.lua.execute("""
            ctx.config.step='advance';state='depart'
            record={status='running',attempts=3,completed_count=2,reserved_energy=9}
            local original=package.loaded['tasks.zhuagui.pages'].state
            reads=0
            package.loaded['tasks.zhuagui.pages'].state=function()
                reads=reads+1
                if reads>=3 then state='ready_cost_three' end
                return original()
            end
        """)
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().record.stage,'one_task_completed')
        self.assertEqual(len(self.lua.globals().taps),0)

    def prepare_weapon_retry(self, retries=0, success_after=100, category='兵器', failure_state='retry'):
        self.lua.globals().test_category=category
        self.lua.globals().failure_state=failure_state
        self.lua.globals().success_after=success_after
        self.lua.execute(f'''
            ctx.config.step='complete';ctx.config.zhuagui_budget=75
            state='find';mSleep=function() end;solve_calls=0
            record={{status='running',attempts=25,completed_count=24,reserved_energy=75,find_retries={retries},find_retry_pending=1}}
            package.preload['tasks.zhuagui.find']=function() return {{solve=function()
                solve_calls=solve_calls+1
                if solve_calls>=success_after then state='quota_completed_card';return true,'find_clicked' end
                state=failure_state;return false,'find_time_expired',test_category
            end}} end
        ''')

    def test_weapon_has_initial_attempt_plus_three_free_retries(self):
        self.prepare_weapon_retry(success_after=4)
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().solve_calls,4)
        self.assertEqual(list(self.lua.globals().taps.values()),['retry']*3)
        self.assertEqual(self.lua.globals().record['reserved_energy'],75)
        self.assertEqual(self.lua.globals().record['find_retries'],3)
        self.assert_no_accept()

    def test_weapon_retry_exhaustion_retains_owned_unfinished_attempt(self):
        self.prepare_weapon_retry()
        self.assertEqual(self.run_task()['reason'],'find_retry_limit')
        self.assertEqual(self.lua.globals().solve_calls,4)
        self.assertEqual(self.lua.globals().record['completed_count'],24)
        self.assertEqual(list(self.lua.globals().taps.values()),['retry']*3)
        self.assert_no_accept()

    def test_failed_find_dialogue_has_the_same_three_retry_limit(self):
        self.prepare_weapon_retry(failure_state='dialogue')
        self.lua.execute("local previous=require('common.device').tap;require('common.device').tap=function(c,f,label) local ok=previous(c,f,label);if f=='dialogue_next' then state='find' end;return ok end")
        self.assertEqual(self.run_task()['reason'],'find_retry_limit')
        self.assertEqual(self.lua.globals().solve_calls,4)
        self.assertEqual(list(self.lua.globals().taps.values()),['dialogue_next']*3)
        self.assertEqual(self.lua.globals().record.find_retries,3)
        self.assert_no_accept()

    def test_failed_find_dialogue_can_retry_and_deliver(self):
        self.prepare_weapon_retry(success_after=2,failure_state='dialogue')
        self.lua.execute("local previous=require('common.device').tap;require('common.device').tap=function(c,f,label) local ok=previous(c,f,label);if f=='dialogue_next' then state='find' end;return ok end")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['dialogue_next'])
        self.assert_no_accept()

    def test_retry_limit_is_retained_within_this_invocation(self):
        self.prepare_weapon_retry(retries=3)
        self.lua.execute("state='retry'")
        self.assertEqual(self.run_task()['reason'],'find_retry_limit')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_fresh_run_recovers_visible_retry_without_old_counter(self):
        self.prepare_weapon_retry(success_after=1)
        self.lua.execute("state='retry';record=nil")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().record.find_retries,1)
        self.assertEqual(list(self.lua.globals().taps.values()),['retry'])
        self.assert_no_accept()

    def test_in_run_retry_requires_observed_failure_and_has_limit(self):
        for retries,pending in [(3,1),(0,0)]:
            self.prepare_weapon_retry(retries=retries)
            self.lua.execute(f"state='retry';record.find_retry_pending={pending}")
            self.assertEqual(self.run_task()['reason'],'find_retry_limit' if pending else 'retry_without_recognition_failure')
            self.assertEqual(len(self.lua.globals().taps),0)

    def test_fresh_recovery_requires_runtime_initialization_before_click(self):
        self.prepare_weapon_retry()
        self.lua.execute("state='retry';record=nil;fail_reservation=true")
        with self.assertRaises(Exception):self.run_task()
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_fresh_recovery_cannot_click_when_paid_accept_is_visible(self):
        self.prepare_weapon_retry()
        self.lua.execute("state='retry';record=nil;paid_accept_visible=true")
        self.assertEqual(self.run_task()['reason'],'free_action_precondition_not_verified')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_runtime_limit_does_not_offer_a_manual_extra_retry(self):
        self.prepare_weapon_retry(retries=3)
        self.lua.execute("state='retry'")
        self.assertEqual(self.run_task()['reason'],'find_retry_limit')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_failed_retry_reservation_prevents_click(self):
        self.prepare_weapon_retry()
        self.lua.execute('fail_reservation=true')
        with self.assertRaises(Exception):self.run_task()
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_other_find_categories_also_have_three_recognition_retries(self):
        self.prepare_weapon_retry(category='书籍',success_after=4)
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['retry']*3)

    def test_retry_page_without_recognition_failure_never_clicks(self):
        self.prepare_weapon_retry()
        self.lua.execute("state='retry';record.find_retry_pending=0")
        self.assertEqual(self.run_task()['reason'],'retry_without_recognition_failure')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_puzzle_retry_page_recovers_without_an_instance_argument(self):
        self.lua.execute("ctx.config.step='complete';state='puzzle_retry';record=nil;mSleep=function() end")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['puzzle_retry'])
        self.assert_no_accept()

    def test_authorized_puzzle_resume_is_free_and_not_repeated(self):
        self.lua.execute("ctx.config.step='complete';state='puzzle_retry';record={status='running',attempts=25,completed_count=24,reserved_energy=75};mSleep=function() end")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['puzzle_retry'])
        self.assertEqual(self.lua.globals().record['reserved_energy'],75)
        self.lua.execute("state='puzzle_retry';record.status='running'")
        self.assertEqual(self.run_task()['reason'],'puzzle_retry_not_authorized')
        self.assertEqual(list(self.lua.globals().taps.values()),['puzzle_retry'])

    def test_old_numeric_target_does_not_stop_before_completion_card(self):
        self.lua.execute("ctx.config.step='complete';ctx.config.zhuagui_target=10;ctx.identity_verified=true;record={status='running',attempts=10,completed_count=9,reserved_energy=30}")
        self.assertNotEqual(self.run_task()['status'],'done')
        self.assertIn('accept',list(self.lua.globals().taps.values()))
        self.assertEqual(self.lua.globals().record.status,'running')

    def test_weapon_retry_does_not_click_paid_or_unknown_page(self):
        for state in ('ready_cost_three','unknown'):
            with self.subTest(state=state):
                self.prepare_weapon_retry(failure_state=state)
                self.assertEqual(self.run_task()['reason'],'find_time_expired')
                self.assertEqual(len(self.lua.globals().taps),0)

    def test_final_quota_dialogue_is_closed_before_completed_stamp_search(self):
        self.lua.execute("ctx.config.step='complete';state='quota_dialogue';completion_card_after_scroll=true;mSleep=function() end;record={status='running',attempts=25,completed_count=24,reserved_energy=75}")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['quota_dialogue','swipe'])
        self.assert_no_accept()

    def test_quota_dialogue_searches_for_completion_card_without_ledger_counts(self):
        self.lua.execute("ctx.config.step='complete';state='quota_dialogue';record={status='running',attempts=24,completed_count=23,reserved_energy=72}")
        self.lua.execute('completion_card_after_scroll=true')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['quota_dialogue','swipe'])

    def test_final_recovery_reopens_completion_list_after_identity_verification(self):
        self.lua.execute('''
            ctx.config.step='complete';ctx.config.verify_role=true
            state='quota_completed_card';completion_card_after_scroll=true;mSleep=function() end
            entry_card_after_scroll=100
            record={status='running',attempts=25,completed_count=24,reserved_energy=75}
            package.preload['common.navigation']=function() return {prepare_recorded=function(c)
                state='home';c.identity_verified=true;return true
            end} end
        ''')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['home_tasks','swipe'])
        self.assert_no_accept()

    def test_final_recovery_from_home_never_reopens_paid_detail(self):
        self.lua.execute("ctx.config.step='complete';ctx.identity_verified=true;state='unknown';completion_card_after_scroll=true;entry_card_after_scroll=100;mSleep=function() end;record={status='running',attempts=25,completed_count=24,reserved_energy=75}")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['home_tasks','swipe'])
        self.assert_no_accept()

    def test_entry_only_returns_home_verifies_identity_and_does_not_accept(self):
        self.lua.execute("ctx.config.step='enter'; state='rules'")
        result = self.run_task()
        self.assertEqual(result['status'], 'running')
        self.assertTrue(self.lua.globals().ctx['identity_verified'])
        self.assertEqual(list(self.lua.globals().taps.values()), ['rules','cancel','home_tab','home_tasks','task_card'])
        self.assert_no_accept()

    def test_hidden_task_card_is_found_by_scrolling_without_accepting(self):
        self.lua.execute("ctx.config.step='enter';state='home';entry_card_after_scroll=2")
        self.assertEqual(self.run_task()['status'],'running')
        self.assertEqual(list(self.lua.globals().taps.values()).count('swipe'),2)
        self.assert_no_accept()

    def test_missing_entry_stops_after_shared_traversal_limit(self):
        self.lua.execute("ctx.config.step='enter';state='home';entry_card_after_scroll=100")
        self.assertEqual(self.run_task()['reason'],'task_card_not_found_after_scroll')
        self.assertEqual(list(self.lua.globals().taps.values()).count('swipe'),24)
        self.assert_no_accept()

    def test_task_list_disappearing_stops_scrolling(self):
        self.lua.execute("ctx.config.step='enter';state='home';entry_card_after_scroll=100;leave_list_on_scroll=true")
        self.assertEqual(self.run_task()['reason'],'task_list_changed')
        self.assertEqual(list(self.lua.globals().taps.values()).count('swipe'),1)
        self.assert_no_accept()

    def test_entry_waits_when_notice_hides_card_before_guarded_tap(self):
        self.lua.execute('''
            ctx.config.step='enter';state='home';activation_attempts=0
            require('common.device').wait=function(predicate,attempts)
                for _=1,attempts do if predicate() then return true end end
                return false
            end
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if label=='zhuagui_open_detail' then
                    activation_attempts=activation_attempts+1
                    if activation_attempts<3 then return false end
                end
                return tap(c,f,label)
            end
        ''')
        self.assertEqual(self.run_task()['status'],'running')
        self.assertEqual(self.lua.globals().activation_attempts,3)
        self.assertEqual(list(self.lua.globals().taps.values()).count('task_card'),1)
        self.assert_no_accept()

    def test_entry_target_staying_hidden_stops_without_sending_a_tap(self):
        self.lua.execute('''
            ctx.config.step='enter';state='home'
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if label=='zhuagui_open_detail' then return false end
                return tap(c,f,label)
            end
        ''')
        self.assertEqual(self.run_task()['reason'],'task_list_changed')
        self.assertNotIn('task_card',list(self.lua.globals().taps.values()))
        self.assert_no_accept()

    def test_reservation_precedes_single_accept(self):
        self.lua.execute('ctx.config.zhuagui_budget=3')
        self.assertEqual(self.run_task()['status'], 'running')
        self.assertEqual(self.lua.globals().record.stage,'start_requested')
        self.assertEqual(list(self.lua.globals().taps.values()).count('accept'), 1)

    def test_verified_role_accepts_next_task_without_leaving_ready_dialogue(self):
        self.lua.execute('ctx.identity_verified=true; ctx.config.zhuagui_budget=3')
        self.assertEqual(self.run_task()['status'],'running')
        self.assertEqual(list(self.lua.globals().taps.values()),['accept'])

    def test_in_place_continuation_does_not_require_matching_count(self):
        self.lua.execute('ctx.identity_verified=true; ctx.config.zhuagui_budget=6; visible_count=0; record={status="paused",stage="one_task_completed",attempts=1,completed_count=1,reserved_energy=3}')
        self.assertEqual(self.run_task()['status'],'running')
        self.assertEqual(list(self.lua.globals().taps.values()),['accept'])

    def test_recovered_role_must_verify_identity_before_recording_completion(self):
        self.lua.execute('''
            ctx.config.step='advance';ctx.config.verify_role=true
            record={status='running',attempts=1,completed_count=0,reserved_energy=3}
            package.preload['common.navigation']=function() return {prepare_recorded=function() return false end} end
        ''')
        self.assertEqual(self.run_task()['reason'],'saved_role_not_ready')
        self.assertEqual(self.lua.globals().record['completed_count'],0)
        self.assert_no_accept()

    def test_reserved_attempt_cannot_be_repeated(self):
        self.lua.execute("ctx.config.zhuagui_budget=15; record={status='running',reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'], 'active_attempt_already_reserved')
        self.assert_no_accept()

    def test_resumption_has_no_fee_cap(self):
        self.lua.execute("ctx.config.zhuagui_budget=3; record={status='paused',reserved_energy=3,attempts=1}")
        self.assertEqual(self.run_task()['status'],'running')
        self.assertIn('accept',list(self.lua.globals().taps.values()))

    def test_failed_identity_never_accepts(self):
        self.lua.execute('ctx.config.zhuagui_budget=15; identity_available=false')
        self.assertEqual(self.run_task()['reason'], 'saved_role_not_ready')
        self.assert_no_accept()

    def test_failed_reservation_never_accepts(self):
        self.lua.execute('ctx.config.zhuagui_budget=3; fail_reservation=true')
        with self.assertRaises(Exception):
            self.run_task()
        self.assert_no_accept()

    def test_unknown_active_page_has_no_actions(self):
        self.lua.execute("ctx.config.step='advance'; state='active_uncalibrated'")
        self.assertEqual(self.run_task()['status'], 'blocked')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_numeric_quota_without_completion_card_does_not_finish(self):
        self.lua.execute("ctx.config.step='complete'; ctx.config.zhuagui_budget=75; record={status='running',attempts=25,completed_count=24,reserved_energy=75}")
        self.assertNotEqual(self.run_task()['status'],'done')
        self.assertIn('accept',list(self.lua.globals().taps.values()))

    def test_advance_records_one_completion_and_stops(self):
        self.lua.execute("ctx.config.step='advance'; record={status='running',attempts=1,completed_count=0,reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().record.stage,'one_task_completed')
        self.assert_no_accept()

    def test_completed_card_confirms_last_completion_without_detail_count(self):
        self.lua.execute("ctx.config.step='complete'; state='quota_completed_card'; missing_count=true; record={status='running',attempts=25,completed_count=24,reserved_energy=75}")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(self.lua.globals().record.stage,'completion_card_verified')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_completed_card_finishes_regardless_of_old_attempt_numbers(self):
        self.lua.execute("ctx.config.step='complete'; state='quota_completed_card'; record={status='running',attempts=24,completed_count=23,reserved_energy=72}")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().record.stage,'completion_card_verified')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_final_list_search_requires_explicit_completed_card(self):
        self.lua.execute("ctx.config.step='complete'; state='task_list'; completion_card_after_scroll=true; record={status='running',attempts=25,completed_count=24,reserved_energy=75}; mSleep=function() end")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(list(self.lua.globals().taps.values()), ['swipe'])

    def test_missing_completed_card_stops_after_bounded_scrolls(self):
        self.lua.execute("ctx.config.step='complete'; state='task_list'; record={status='running',attempts=25,completed_count=24,reserved_energy=75}; mSleep=function() end")
        self.assertEqual(self.run_task()['reason'], 'completed_card_not_found')
        self.assertEqual(self.lua.globals().record['completed_count'], 24)
        self.assertEqual(list(self.lua.globals().taps.values()), ['swipe'] * 24)

    def test_completion_scan_returning_to_ready_verifies_delivery_without_accepting(self):
        self.lua.execute('''
            ctx.config.step='advance';state='task_list';record={status='running'}
            local sleep=mSleep
            mSleep=function(ms)
                sleep(ms)
                if ms==150 then state='ready_cost_three' end
            end
        ''')
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().record.stage,'one_task_completed')
        self.assertEqual(len(self.lua.globals().taps),0)
        self.assertIn('clear',list(self.lua.globals().material_events.values()))

    def test_completion_scan_leaving_for_an_unknown_page_still_stops(self):
        self.lua.execute('''
            ctx.config.step='advance';state='task_list';record={status='running'}
            local sleep=mSleep
            mSleep=function(ms)
                sleep(ms)
                if ms==150 then state='unknown' end
            end
        ''')
        self.assertEqual(self.run_task()['reason'],'completion_list_changed')
        self.assertEqual(len(self.lua.globals().taps),0)
        self.assertNotEqual(self.lua.globals().record.status,'done')

    def test_idle_return_is_partial_and_does_not_finish_the_daily_task(self):
        self.lua.execute("ctx.config.step='advance'; visible_count=0; record={status='running',attempts=1,completed_count=0,reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertNotEqual(self.lua.globals().record.status,'done')
        self.assert_no_accept()

    def test_missing_task_digits_do_not_block_idle_return(self):
        self.lua.execute("ctx.config.step='advance'; missing_count=true; record={status='running',attempts=1,completed_count=0,reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertNotEqual(self.lua.globals().record.status,'done')
        self.assert_no_accept()

    def test_recorded_completion_is_not_counted_twice(self):
        self.lua.execute("ctx.config.step='advance'; record={status='paused',stage='one_task_completed',attempts=1,completed_count=1,reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().record['completed_count'],1)
        self.assert_no_accept()

    def test_home_entry_can_resume_existing_npc_without_accepting(self):
        self.lua.execute("ctx.config.step='enter'; state='home'; home_entry_state='go'; record={status='running',attempts=5,completed_count=4,reserved_energy=15}")
        self.assertEqual(self.run_task()['reason'],'existing_task_resumed_no_accept')
        self.assertEqual(list(self.lua.globals().taps.values()),['home_tasks'])
        self.assertEqual(self.lua.globals().record['attempts'],5)
        self.assert_no_accept()

    def test_direct_active_entry_uses_the_visible_task(self):
        self.lua.execute("ctx.config.step='enter';state='go'")
        self.assertEqual(self.run_task()['reason'],'existing_task_resumed_no_accept')
        self.assertEqual(len(self.lua.globals().taps),0)
        self.assertEqual(self.lua.globals().record.stage,'active_page_observed')

    def test_home_entry_recovers_an_existing_task_without_accepting(self):
        self.lua.execute("ctx.config.step='enter';state='home';home_entry_state='go'")
        self.assertEqual(self.run_task()['reason'],'existing_task_resumed_no_accept')
        self.assert_no_accept()


class ScreenCoordinatesTest(unittest.TestCase):
    def test_paid_ready_combination_wins_over_free_depart_button_match(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        lua.execute("""
            package.preload['common.detector']=function() return {present=function(f)
                return visible[f]==true
            end} end
            pages=require('tasks.zhuagui.pages');visible={}
            for _,name in ipairs({'title','idle','cost_three','accept','depart'}) do
                visible[pages.features[name]]=true
            end
        """)
        self.assertEqual(lua.globals().pages.state(),'ready_cost_three')

    def test_landscape_size_uses_initial_orientation_dimensions(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        lua.execute('getScreenSize=function() return 900,1600 end; init=function() end')
        screen = lua.eval("require('common.screen')")[0]
        self.assertEqual(screen.size(), (900,1600))
        for direction in (1,2):
            screen.init(direction)
            self.assertEqual(screen.size(), (1600,900))
        screen.init(0)
        self.assertEqual(screen.size(), (900,1600))


if __name__ == '__main__':
    unittest.main()
