"""Exercise Lua control flow with fake device I/O; never touches a real account."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class DungeonGuardTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            state='unknown'; records={}; taps={}; clock=0
            os.time=function() return clock end
            mSleep=function(ms) clock=clock+ms/1000 end
            keepScreen=function() end
            getColor=function() return (position or 0)*0x001010 end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function() return 'fake.png' end} end
            package.preload['common.navigation']=function() return {
                open_dungeon=function() return false end,return_home=function() return false end} end
            package.preload['common.assets.home_dungeon']=function() return {} end
            package.preload['common.detector']=function() return {present=function(f) return f=='claim' and verified_claim_cost==true end} end
            package.preload['tasks.dungeon.assets.claim_cost_100']=function() return 'claim' end
            package.preload['tasks.dungeon.assets.overview_claim']=function() return 'open_claim' end
            package.preload['progress']=function() return {
                read=function(ctx,id) return records[id] end,
                write=function(ctx,id,status,stage,counters)
                    records[id]={status=status,stage=stage}
                    if counters then for k,v in pairs(counters) do records[id][k]=v end end
                end
            } end
            package.preload['tasks.dungeon.pages']=function() return {
                definitions={wuji={card={}},chechi={card={}}},
                state=function() return state end,
                reward_claimed=function(id) return claimed and claimed[id]==true or false end,
                features={start='start',overview_back='back',switch_wuji_chechi='switch',list='list',claim_confirm_button='confirm_claim'}
            } end
            package.preload['common.device']=function() return {
                tap=function(ctx,feature,label)
                    if feature=='start' then assert(records.wuji and records.wuji.status=='running') end
                    if feature=='claim' then assert(records.wuji.stage=='reward_claim_requested') end
                    if feature=='confirm_claim' then assert(records.wuji.stage=='reward_confirmation_requested') end
                    table.insert(taps,feature)
                    if feature=='back' then state='wuji_done' end
                    if feature=='claim' then state='wuji_claim_confirm' end
                    if feature=='confirm_claim' then state='wuji_done' end
                    return true
                end,
                wait=function(predicate) return predicate() end,
                swipe=function() error('unexpected swipe') end
            } end
            ctx={config={allow_reward_claim=false,step='complete',dungeon='wuji',business_date=os.date('%Y%m%d')},
                 account={alias='fake'},identity_verified=true}
        ''')
        self.task = self.lua.eval("require('tasks.dungeon.task')")[0]

    def run_task(self):
        return self.task.run(self.lua.globals().ctx)

    def test_reserves_attempt_before_start(self):
        self.lua.execute("state='wuji_ready'; ctx.config.step='start'")
        self.assertEqual(self.run_task()['status'], 'running')
        self.assertEqual(self.lua.globals().records['wuji']['status'], 'running')
        self.assertEqual(list(self.lua.globals().taps.values()), ['start'])

    def test_never_restarts_recorded_attempt(self):
        self.lua.execute("state='wuji_ready'; records.wuji={status='running',stage='start_requested'}; ctx.config.step='start'")
        self.assertEqual(self.run_task()['status'], 'blocked')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_observed_carryover_does_not_count_as_today_start(self):
        self.lua.execute("state='wuji_ready'; records.wuji={status='observed',stage='completion_date_unverified'}; ctx.config.step='start'")
        self.assertEqual(self.run_task()['status'], 'running')
        self.assertEqual(list(self.lua.globals().taps.values()), ['start'])

    def test_observed_carryover_cannot_adopt_battle(self):
        self.lua.execute("state='battle'; records.wuji={status='observed',stage='completion_date_unverified'}")
        self.assertEqual(self.run_task()['reason'], 'dungeon_timeout')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_cannot_abandon_uncompleted_wuji(self):
        self.lua.execute("state='switch_wuji_chechi'; ctx.config.step='switch'; ctx.config.dungeon='chechi'")
        self.assertEqual(self.run_task()['status'], 'blocked')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_reverse_switch_requires_verified_chechi_completion(self):
        self.lua.execute("state='switch_chechi_wuji'; ctx.config.step='switch'; ctx.config.dungeon='wuji'; require('tasks.dungeon.pages').features.switch_chechi_wuji='reverse'")
        self.assertEqual(self.run_task()['status'], 'blocked')
        self.assertEqual(len(self.lua.globals().taps), 0)
        self.lua.execute("records.chechi={status='done'}")
        self.lua.execute('ctx.identity_verified=false')
        self.assertEqual(self.run_task()['status'], 'blocked')
        self.assertEqual(len(self.lua.globals().taps), 0)
        self.lua.execute('ctx.identity_verified=true')
        self.assertEqual(self.run_task()['reason'], 'switched_without_claiming_reward')
        self.assertEqual(list(self.lua.globals().taps.values()), ['reverse'])

    def test_completion_only_clicks_back(self):
        self.lua.execute("state='wuji_reward_sealed'; ctx.config.step='finish'; records.wuji={status='running'}")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(list(self.lua.globals().taps.values()), ['back'])
        self.assertEqual(self.lua.globals().records['wuji']['stage'], 'reward_intentionally_unclaimed')

    def test_completion_waits_for_automatic_sealed_page_transition(self):
        self.lua.execute('''
            state='unknown'; calls=0; ctx.config.step='finish'; records.wuji={status='running'}
            require('tasks.dungeon.pages').state=function()
                calls=calls+1
                if state=='wuji_done' then return state end
                return calls<3 and 'unknown' or 'wuji_reward_sealed'
            end
            require('common.device').wait=function(predicate,attempts)
                for _=1,attempts do if predicate() then return true end end
                return false
            end
        ''')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['back'])

    def test_unverified_completion_transition_does_not_mark_done(self):
        self.lua.execute("state='unknown'; ctx.config.step='finish'; records.wuji={status='running'}")
        self.assertEqual(self.run_task()['reason'],'completion_not_verified')
        self.assertEqual(self.lua.globals().records.wuji.status,'running')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_done_runtime_records_do_not_skip_game_page_verification(self):
        self.lua.execute("ctx.config.step='daily';records.wuji={status='done'};records.chechi={status='done'}")
        self.assertEqual(self.run_task()['status'],'blocked')
        self.assertEqual(len(self.lua.globals().taps),0)

    def configure_completed_landing(self, landing, back_state='list_wuji'):
        self.lua.execute(f'''
            ctx.config.step='daily';ctx.config.dungeons={{'wuji'}}
            records.wuji={{status='running'}}
            require('common.detector').present=function(feature)
                return state=='unknown' or (feature=='enter' and state=='list_wuji')
            end
            require('common.navigation').open_dungeon=function()
                state='{landing}'; return true
            end
            require('common.device').tap=function(ctx,feature,label)
                table.insert(taps,feature)
                if feature=='back' then
                    if state=='chechi_reward_sealed' then state='chechi_done'
                    else state='{back_state}' end
                end
                if feature=='enter' then state='wuji_done' end
                return true
            end
            require('tasks.dungeon.pages').features.enter='enter'
        ''')

    def test_home_entry_restores_completed_other_dungeon(self):
        self.configure_completed_landing('chechi_done')
        self.lua.execute("records.chechi={status='done'}")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(list(self.lua.globals().taps.values()), ['back', 'enter'])
        self.assertEqual(self.lua.globals().records.wuji.stage, 'reward_intentionally_unclaimed')

    def test_unowned_completed_other_dungeon_is_only_observed(self):
        self.configure_completed_landing('chechi_done')
        # Stop on the next task to inspect the earlier recovery record.
        self.lua.execute("require('common.navigation').open_dungeon=function() state='chechi_done'; return true end")
        self.lua.execute("require('common.device').swipe=function() return false end")
        self.run_task()
        self.assertEqual(self.lua.globals().records.chechi.status, 'done')
        self.assertEqual(self.lua.globals().records.chechi.stage, 'reward_intentionally_unclaimed')

    def test_home_entry_restores_completed_target_without_starting(self):
        self.configure_completed_landing('wuji_done')
        self.lua.execute("records.chechi={status='done'}")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_home_entry_restores_sealed_other_dungeon(self):
        self.configure_completed_landing('chechi_reward_sealed')
        self.lua.execute("records.chechi={status='done'}")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(list(self.lua.globals().taps.values()), ['back', 'back', 'enter'])

    def test_home_entry_restores_sealed_target_without_claiming(self):
        self.configure_completed_landing('wuji_reward_sealed', 'wuji_done')
        self.lua.execute("records.chechi={status='done'}")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(list(self.lua.globals().taps.values()), ['back'])

    def test_return_from_completed_other_dungeon_requires_list(self):
        self.configure_completed_landing('chechi_done', 'unknown')
        self.lua.execute('records.wuji=nil')
        self.assertEqual(self.run_task()['reason'], 'dungeon_return_list_not_verified')
        self.assertEqual(list(self.lua.globals().taps.values()), ['back'])
        self.assertIsNone(self.lua.globals().records.wuji)

    def test_carousel_searches_both_sides_of_initial_position(self):
        self.lua.execute('''
            ctx.config.step='daily';ctx.config.dungeons={'wuji'}; records.chechi={status='done'}; records.wuji={status='running'}
            position=3; swipes=0; state='list_other'
            local pages=require('tasks.dungeon.pages')
            pages.features.enter='enter'; pages.features.list='list'
            pages.state=function()
                if state=='wuji_done' then return state end
                return position==0 and 'list_wuji' or 'list_other'
            end
            require('common.detector').present=function(feature)
                return feature=='enter' and position==0
            end
            require('common.device').swipe=function(ctx,feature,label,from,to)
                assert(feature=='list')
                position=position+(from[1]>to[1] and 1 or -1)
                swipes=swipes+1; return true
            end
            require('common.device').tap=function(ctx,feature,label)
                assert(feature=='enter'); table.insert(taps,feature)
                state='wuji_done'; return true
            end
        ''')
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(self.lua.globals().swipes, 19)
        self.assertEqual(list(self.lua.globals().taps.values()), ['enter'])

    def test_role_reward_request_is_reserved_before_single_click(self):
        self.lua.execute("state='wuji_reward_sealed'; ctx.config.step='finish'; records.wuji={status='running'}; ctx.account.claim_dungeon_rewards=true; ctx.account.dungeon_reward_budget=200; verified_claim_cost=true")
        self.assertEqual(self.run_task()['reason'],'reward_claim_not_verified_no_repeat')
        self.assertEqual(list(self.lua.globals().taps.values()),['claim','confirm_claim'])
        self.assertEqual(self.lua.globals().records.wuji.stage,'reward_confirmation_requested')
        self.assertEqual(self.run_task()['reason'],'reward_claim_not_verified_no_repeat')
        self.assertEqual(list(self.lua.globals().taps.values()),['claim','confirm_claim'])

    def test_authorized_reward_uses_no_cross_dungeon_fee_budget(self):
        self.lua.execute("state='wuji_reward_sealed'; ctx.config.step='finish'; records.wuji={status='running'}; ctx.account.claim_dungeon_rewards=true; ctx.account.dungeon_reward_budget=100; records.chechi={status='done',reward_cost_reserved=100}; verified_claim_cost=true")
        self.assertEqual(self.run_task()['reason'],'reward_claim_not_verified_no_repeat')
        self.assertEqual(list(self.lua.globals().taps.values()),['claim','confirm_claim'])

    def test_reward_requires_role_identity_and_exact_cost(self):
        self.lua.execute("state='wuji_reward_sealed'; ctx.config.step='finish'; records.wuji={status='running'}; ctx.account.claim_dungeon_rewards=true; ctx.account.dungeon_reward_budget=200; ctx.identity_verified=false")
        self.assertEqual(self.run_task()['reason'],'completion_role_identity_not_verified')
        self.lua.execute('ctx.identity_verified=true')
        self.assertEqual(self.run_task()['reason'],'reward_cost_requires_calibration')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_completion_requires_the_current_business_date(self):
        self.lua.execute("state='wuji_done';ctx.config.step='finish';ctx.config.business_date='19000101'")
        self.assertEqual(self.run_task()['reason'],'completion_not_verified')
        self.assertIsNone(self.lua.globals().records.wuji)
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_terminal_state_for_verified_role_and_date_finishes_without_start_history(self):
        self.lua.execute("state='wuji_reward_sealed';ctx.config.step='finish';ctx.config.business_date=os.date('%Y%m%d')")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().records.wuji.stage,'reward_intentionally_unclaimed')
        self.assertEqual(list(self.lua.globals().taps.values()),['back'])

    def test_unclaimed_record_does_not_satisfy_role_that_requires_reward(self):
        self.lua.execute("state='wuji_done'; ctx.account.claim_dungeon_rewards=true; records.wuji={status='done',stage='reward_intentionally_unclaimed'}")
        self.assertEqual(self.run_task()['reason'],'sealed_reward_entry_requires_calibration')
        self.assertEqual(list(self.lua.globals().taps.values()),['open_claim'])

    def configure_sealed_reentry(self, destination):
        self.lua.globals().reentry_destination=destination
        self.lua.execute('''
            state='wuji_done';ctx.config.step='finish';ctx.account.claim_dungeon_rewards=true
            verified_claim_cost=true;home_returns=0;reentries=0
            local navigation=require('common.navigation')
            navigation.return_home=function()
                home_returns=home_returns+1;state='home';return true
            end
            navigation.open_dungeon=function()
                reentries=reentries+1;state=reentry_destination;return true
            end
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                local ok=tap(c,f,label)
                if f=='confirm_claim' then state='list_wuji';claimed={wuji=true} end
                return ok
            end
        ''')

    def test_unchanged_completed_overview_reenters_once_before_claiming(self):
        self.configure_sealed_reentry('wuji_reward_sealed')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['open_claim','claim','confirm_claim'])
        self.assertEqual(self.lua.globals().home_returns,1)
        self.assertEqual(self.lua.globals().reentries,1)
        self.assertEqual(self.lua.globals().records.wuji.stage,'reward_claimed')

    def test_reentry_still_on_overview_stops_without_second_open_or_claim(self):
        self.configure_sealed_reentry('wuji_done')
        self.assertEqual(self.run_task()['reason'],'sealed_reward_entry_requires_calibration')
        self.assertEqual(list(self.lua.globals().taps.values()),['open_claim'])
        self.assertEqual(self.lua.globals().reentries,1)
        self.assertIsNone(self.lua.globals().records.wuji)

    def test_unknown_opening_result_cannot_trigger_reentry_or_claim(self):
        self.configure_sealed_reentry('wuji_reward_sealed')
        self.lua.execute('''
            require('common.device').tap=function(c,f,label)
                taps[#taps+1]=f;state='unknown';return true
            end
        ''')
        self.assertEqual(self.run_task()['reason'],'sealed_reward_entry_requires_calibration')
        self.assertEqual(list(self.lua.globals().taps.values()),['open_claim'])
        self.assertEqual(self.lua.globals().home_returns,0)
        self.assertEqual(self.lua.globals().reentries,0)
        self.assertIsNone(self.lua.globals().records.wuji)

    def test_cold_list_marks_skip_both_completed_dungeons_without_entering(self):
        self.lua.execute("state='list_wuji';claimed={wuji=true,chechi=true};ctx.config.step='daily';ctx.account.claim_dungeon_rewards=true")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(len(self.lua.globals().taps),0)
        self.assertEqual(self.lua.globals().records.wuji.stage,'reward_claimed')
        self.assertEqual(self.lua.globals().records.chechi.stage,'reward_claimed')

    def test_other_dungeons_mark_cannot_prove_the_target_complete(self):
        self.lua.execute("state='list_wuji';claimed={chechi=true};ctx.account.claim_dungeon_rewards=true")
        self.assertEqual(self.run_task()['reason'],'entry_button_not_verified')
        self.assertIsNone(self.lua.globals().records.wuji)
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_list_mark_requires_identity_and_current_day(self):
        self.lua.execute("state='list_wuji';claimed={wuji=true};ctx.identity_verified=false")
        self.assertEqual(self.run_task()['reason'],'claimed_card_not_verified')
        self.lua.execute("ctx.identity_verified=true;ctx.config.business_date='19000101'")
        self.assertEqual(self.run_task()['reason'],'claimed_card_not_verified')
        self.assertIsNone(self.lua.globals().records.wuji)
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_automatic_receipt_close_uses_the_list_postcondition(self):
        self.lua.execute('''
            state='wuji_reward_sealed';ctx.config.step='finish';verified_claim_cost=true
            ctx.account.claim_dungeon_rewards=true
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                local ok=tap(c,f,label)
                if f=='confirm_claim' then state='list_wuji';claimed={wuji=true} end
                return ok
            end
        ''')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['claim','confirm_claim'])
        self.assertEqual(self.lua.globals().records.wuji.stage,'reward_claimed')
        self.lua.execute("ctx.config.step='complete'")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['claim','confirm_claim'])

    def test_unknown_page_cannot_be_hidden_by_a_runtime_record(self):
        self.lua.execute("records.wuji={status='running'}")
        self.assertEqual(self.run_task()['reason'],'active_dungeon_page_not_verified')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_receipt_audit_scrolls_to_claimed_marker_despite_selected_title(self):
        self.lua.execute('''
            state='wuji_reward_sealed';ctx.config.step='finish';verified_claim_cost=true
            ctx.account.claim_dungeon_rewards=true;position=0;swipes=0
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                local ok=tap(c,f,label)
                if f=='confirm_claim' then state='list_wuji' end
                return ok
            end
            require('common.device').swipe=function()
                swipes=swipes+1;position=1;claimed={wuji=true};return true
            end
        ''')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().swipes,1)
        self.assertEqual(list(self.lua.globals().taps.values()),['claim','confirm_claim'])
        self.assertEqual(self.lua.globals().records.wuji.stage,'reward_claimed')

    def test_five_stage_dungeon_can_finish_after_thirty_minutes(self):
        self.lua.execute('''
            state='battle'; records.wuji={status='running'}
            require('tasks.dungeon.pages').state=function()
                return clock>=2100 and 'wuji_done' or 'battle'
            end
        ''')
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(self.lua.globals().clock, 2100)
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_explicit_battle_wait_limit_preserves_owned_attempt(self):
        self.lua.execute("state='battle'; records.wuji={status='running'}; ctx.config.dungeon_timeout=10")
        self.assertEqual(self.run_task()['reason'], 'dungeon_timeout')
        self.assertEqual(self.lua.globals().clock, 10)
        self.assertEqual(self.lua.globals().records.wuji.status, 'running')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_visible_battle_resumes_without_starting_again(self):
        self.lua.execute("state='battle';ctx.config.dungeon_timeout=10")
        self.assertEqual(self.run_task()['reason'],'dungeon_timeout')
        self.assertEqual(self.lua.globals().clock,10)
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_visible_active_overview_resumes_without_a_start_record(self):
        self.lua.execute('''
            state='wuji_active'
            require('tasks.dungeon.pages').features.continue_battle='continue_battle'
            require('common.detector').present=function(f) return f=='continue_battle' end
            require('common.device').tap=function(c,f,label,guard)
                assert(f=='continue_battle' and guard());taps[#taps+1]=f
                state='wuji_done';return true
            end
        ''')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['continue_battle'])

    def test_resume_requires_the_battle_postcondition(self):
        self.lua.execute('''
            state='wuji_active'
            require('tasks.dungeon.pages').features.continue_battle='continue_battle'
            require('common.detector').present=function(f) return f=='continue_battle' end
        ''')
        self.assertEqual(self.run_task()['reason'],'continue_battle_postcondition_not_verified')
        self.assertIsNone(self.lua.globals().records.wuji)
        self.assertEqual(list(self.lua.globals().taps.values()),['continue_battle'])

    def test_unexpected_active_dungeon_is_not_resumed(self):
        self.lua.execute("state='chechi_active'")
        self.assertEqual(self.run_task()['reason'],'active_dungeon_page_not_verified')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_launch_notice_waits_until_the_resume_control_is_visible(self):
        self.lua.execute('''
            state='wuji_active';button_checks=0
            require('tasks.dungeon.pages').features.continue_battle='continue_battle'
            require('common.detector').present=function(f)
                if f~='continue_battle' then return false end
                button_checks=button_checks+1;return button_checks>=4
            end
            require('common.device').wait=function(predicate,attempts,interval)
                for _=1,attempts do if predicate() then return true end;mSleep(interval or 500) end
                return false
            end
            require('common.device').tap=function(c,f,label,guard)
                assert(f=='continue_battle' and guard());taps[#taps+1]=f;state='wuji_done';return true
            end
        ''')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(list(self.lua.globals().taps.values()),['continue_battle'])
        self.assertAlmostEqual(self.lua.globals().clock,0.9)

    def test_invisible_resume_button_stops_without_a_click(self):
        self.lua.execute("state='wuji_active';require('tasks.dungeon.pages').features.continue_battle='continue_battle'")
        self.assertEqual(self.run_task()['reason'],'continue_battle_button_not_visible')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_auto_transition_during_guarded_resume_does_not_pause(self):
        self.lua.execute('''
            state='wuji_active'
            require('tasks.dungeon.pages').features.continue_battle='continue_battle'
            require('common.detector').present=function(f) return f=='continue_battle' end
            require('common.device').tap=function() state='wuji_done';return false end
        ''')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_started_dungeon_observes_automatic_stages_without_any_click(self):
        self.lua.execute('''
            state='battle'
            require('tasks.dungeon.pages').state=function()
                if clock>=8 then return 'wuji_done' end
                if clock>=2 and clock<4 then return 'wuji_active' end
                return 'battle'
            end
            require('common.detector').present=function() return false end
            require('common.device').tap=function() error('automatic dungeon must not click') end
        ''')
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_interrupted_automatic_dungeon_stops_after_bounded_observation(self):
        self.lua.execute("ctx.config.step='advance';state='wuji_active'")
        self.assertEqual(self.run_task()['reason'],'dungeon_interrupted')
        self.assertEqual(self.lua.globals().clock,30)
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_reward_claim_policy_cannot_be_enabled(self):
        self.lua.execute('ctx.config.allow_reward_claim=true')
        with self.assertRaises(Exception):
            self.run_task()
        self.assertEqual(len(self.lua.globals().taps), 0)


if __name__ == '__main__':
    unittest.main()
