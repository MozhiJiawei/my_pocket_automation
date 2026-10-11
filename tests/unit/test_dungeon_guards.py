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
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function() return 'fake.png' end} end
            package.preload['common.navigation']=function() return {open_dungeon=function() return false end} end
            package.preload['common.assets.home_dungeon']=function() return {} end
            package.preload['common.detector']=function() return {present=function() return verified_claim_cost==true end} end
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
                features={start='start',overview_back='back',switch_wuji_chechi='switch'}
            } end
            package.preload['common.device']=function() return {
                tap=function(ctx,feature,label)
                    if feature=='start' then assert(records.wuji and records.wuji.status=='running') end
                    if feature=='claim' then assert(records.wuji.stage=='reward_claim_requested' and records.wuji.reward_cost_reserved==100) end
                    table.insert(taps,feature)
                    if feature=='back' then state='wuji_done' end
                    return true
                end,
                wait=function(predicate) return predicate() end,
                swipe=function() error('unexpected swipe') end
            } end
            ctx={config={allow_reward_claim=false,step='complete',dungeon='wuji'},
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
        self.lua.execute("state='wuji_ready'; records.wuji={status='running'}; ctx.config.step='start'")
        self.assertEqual(self.run_task()['status'], 'blocked')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_observed_carryover_does_not_count_as_today_start(self):
        self.lua.execute("state='wuji_ready'; records.wuji={status='observed',stage='completion_date_unverified'}; ctx.config.step='start'")
        self.assertEqual(self.run_task()['status'], 'running')
        self.assertEqual(list(self.lua.globals().taps.values()), ['start'])

    def test_observed_carryover_cannot_adopt_battle(self):
        self.lua.execute("state='battle'; records.wuji={status='observed',stage='completion_date_unverified'}")
        self.assertEqual(self.run_task()['reason'], 'active_dungeon_ownership_not_recorded')
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

    def test_done_daily_tasks_skip_without_device_actions(self):
        self.lua.execute("ctx.config.step='daily'; records.wuji={status='done'}; records.chechi={status='done'}")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def configure_completed_landing(self, landing, back_state='list_wuji'):
        self.lua.execute(f'''
            ctx.config.step='daily'
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
        self.assertEqual(self.lua.globals().records.chechi.status, 'observed')
        self.assertEqual(self.lua.globals().records.chechi.stage, 'completion_date_unverified')

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
            ctx.config.step='daily'; records.chechi={status='done'}; records.wuji={status='running'}
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
        self.assertEqual(self.lua.globals().swipes, 13)
        self.assertEqual(list(self.lua.globals().taps.values()), ['enter'])

    def test_role_reward_request_is_reserved_before_single_click(self):
        self.lua.execute("state='wuji_reward_sealed'; ctx.config.step='finish'; records.wuji={status='running'}; ctx.account.claim_dungeon_rewards=true; ctx.account.dungeon_reward_budget=200; verified_claim_cost=true")
        self.assertEqual(self.run_task()['reason'],'reward_receipt_requires_calibration_no_repeat')
        self.assertEqual(list(self.lua.globals().taps.values()),['claim'])
        self.assertEqual(self.lua.globals().records.wuji.reward_cost_reserved,100)
        self.assertEqual(self.run_task()['reason'],'reward_receipt_requires_calibration_no_repeat')
        self.assertEqual(list(self.lua.globals().taps.values()),['claim'])

    def test_reward_budget_counts_both_dungeons(self):
        self.lua.execute("state='wuji_reward_sealed'; ctx.config.step='finish'; records.wuji={status='running'}; ctx.account.claim_dungeon_rewards=true; ctx.account.dungeon_reward_budget=100; records.chechi={status='done',reward_cost_reserved=100}; verified_claim_cost=true")
        self.assertEqual(self.run_task()['reason'],'dungeon_reward_budget_exhausted')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_reward_requires_role_identity_and_exact_cost(self):
        self.lua.execute("state='wuji_reward_sealed'; ctx.config.step='finish'; records.wuji={status='running'}; ctx.account.claim_dungeon_rewards=true; ctx.account.dungeon_reward_budget=200; ctx.identity_verified=false")
        self.assertEqual(self.run_task()['reason'],'reward_role_identity_not_verified')
        self.lua.execute('ctx.identity_verified=true')
        self.assertEqual(self.run_task()['reason'],'reward_cost_requires_calibration')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_unowned_completion_cannot_prove_today_success(self):
        self.lua.execute("state='wuji_done'; ctx.config.step='finish'")
        self.assertEqual(self.run_task()['reason'],'completion_date_not_verified')
        self.assertEqual(self.lua.globals().records.wuji.status,'observed')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_unclaimed_record_does_not_satisfy_role_that_requires_reward(self):
        self.lua.execute("state='wuji_done'; ctx.account.claim_dungeon_rewards=true; records.wuji={status='done',stage='reward_intentionally_unclaimed'}")
        self.assertEqual(self.run_task()['reason'],'sealed_reward_entry_requires_calibration')
        self.assertEqual(list(self.lua.globals().taps.values()),['open_claim'])

    def test_unknown_resume_is_bounded_without_clicking(self):
        self.lua.execute("records.wuji={status='running'}")
        self.assertEqual(self.run_task()['status'], 'paused')
        self.assertLessEqual(self.lua.globals().clock, 31)
        self.assertEqual(len(self.lua.globals().taps), 0)

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

    def test_unowned_battle_cannot_be_adopted(self):
        self.lua.execute("state='battle'")
        self.assertEqual(self.run_task()['status'], 'blocked')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_reward_claim_policy_cannot_be_enabled(self):
        self.lua.execute('ctx.config.allow_reward_claim=true')
        with self.assertRaises(Exception):
            self.run_task()
        self.assertEqual(len(self.lua.globals().taps), 0)


if __name__ == '__main__':
    unittest.main()
