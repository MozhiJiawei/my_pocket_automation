"""Reward prerequisites use real Lua task code and role/date-scoped storage."""
from pathlib import Path
import unittest

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class RewardsFixture(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            files={}; taps={}; captures={}; page_reads=0; state='unknown'
            ctx={config={business_date='20261014',step='daily',dungeons={'wuji','chechi'}},
                account={alias='first'},run_id='test',identity_verified=true}
            other={config={business_date='20261014'},account={alias='second'},run_id='other'}
            io.open=function(path,mode)
                if mode=='r' and not files[path] then return nil end
                return {
                    write=function(self,value) files[path]=value;return true end,
                    close=function() return true end
                }
            end
            os.rename=function(source,target)
                files[target]=files[source];files[source]=nil;return true
            end
            loadfile=function(path) return load(files[path]) end
            package.preload['tasks.rewards.pages']=function()
                local features={}
                for _,name in ipairs({'inventory','task_tab','task_tab_selected','dungeon_tab',
                    'special_tab','special_tab_selected','bag_tab','treasury_tab','zhuagui_card',
                    'shimen_card','no_cost','detail_title','detail_back','open_one','discard'}) do
                    features[name]=name
                end
                return {
                    state=function() page_reads=page_reads+1;return state end,
                    count=function() return visible_count end,
                    free_card=function() return true end,
                    features=features,
                    items={
                        {id=1,name='zhuagui',tab='task',card=features.zhuagui_card,cost=0},
                        {id=2,name='shimen',tab='task',card=features.shimen_card,cost=0},
                    }
                }
            end
            package.preload['tasks.shimen.pages']=function() return {
                state=function() page_reads=page_reads+1;return state end,
                count=function() return nil end,features={},actions={}
            } end
            package.preload['common.detector']=function() return {
                present=function() error('prerequisites must not infer completion from a detector') end
            } end
            package.preload['common.device']=function() return {
                tap=function(c,feature,label) table.insert(taps,label);return false end,
                wait=function(predicate) return predicate() end
            } end
            package.preload['common.navigation']=function() return {
                prepare_recorded=function() return false end
            } end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {
                capture=function(c,label) table.insert(captures,label) end
            } end
        ''')
        self.progress = self.lua.eval("require('progress')")[0]
        self.task = self.lua.eval("require('tasks.rewards.task')")[0]
        self.ctx = self.lua.globals().ctx

    def write(self, task, status, stage, counters=None, ctx=None, date=None):
        self.progress.write(
            self.ctx if ctx is None else ctx, task, status, stage,
            self.lua.table_from(counters or {}), date,
        )

    def valid_records(self, ctx=None, date=None):
        self.write('shimen', 'done', 'delivery_verified',
                   {'attempts': 20, 'completed_count': 20}, ctx, date)
        self.write('zhuagui', 'done', 'all_25_completed_gourds_unopened',
                   {'attempts': 25, 'completed_count': 25}, ctx, date)
        for task in ('wuji', 'chechi'):
            self.write(task, 'done', 'reward_intentionally_unclaimed', ctx=ctx, date=date)

    def assert_rejected(self, reason):
        self.assertEqual(self.task.prerequisites(self.ctx), (False, reason))
        self.assertEqual(len(self.lua.globals().taps), 0)
        self.assertEqual(self.lua.globals().page_reads, 0)


class RewardsGuardTest(RewardsFixture):
    def test_missing_all_ledgers_is_rejected(self):
        self.assert_rejected('shimen_not_verified_complete')

    def test_each_missing_required_ledger_is_rejected(self):
        for task in ('shimen', 'zhuagui', 'wuji', 'chechi'):
            with self.subTest(task=task):
                self.valid_records()
                self.lua.globals().files[
                    f'/storage/emulated/0/TouchSprite/res/daily_progress_20261014_first_{task}.lua'
                ] = None
                self.assert_rejected(f'{task}_not_verified_complete')

    def test_verified_full_ledgers_are_accepted_without_screen_actions(self):
        self.valid_records()
        self.assertIs(self.task.prerequisites(self.ctx), True)
        self.assertEqual(len(self.lua.globals().taps), 0)
        self.assertEqual(self.lua.globals().page_reads, 0)

    def test_shimen_requires_exact_twenty_attempts_and_deliveries(self):
        self.valid_records()
        for attempts, completed in ((None, 20), (20, None), (19, 20), (20, 19),
                                    (21, 20), (20, 21), (20, 0)):
            with self.subTest(attempts=attempts, completed=completed):
                counters = {key: value for key, value in (
                    ('attempts', attempts), ('completed_count', completed)
                ) if value is not None}
                self.write('shimen', 'done', 'delivery_verified', counters)
                self.assert_rejected('shimen_not_verified_complete')

    def test_shimen_accepts_only_verified_delivery_stages(self):
        self.valid_records()
        for stage in ('delivery_verified', 'completion_card_verified', 'one_task_completed'):
            with self.subTest(stage=stage):
                self.write('shimen', 'done', stage, {'attempts': 20, 'completed_count': 20})
                self.assertIs(self.task.prerequisites(self.ctx), True)
        for stage in ('', 'accept_reserved', 'find_exit_requires_delivery_verification',
                      'puzzle_exit_requires_delivery_verification'):
            with self.subTest(stage=stage):
                self.write('shimen', 'done', stage, {'attempts': 20, 'completed_count': 20})
                self.assert_rejected('shimen_not_verified_complete')

    def test_shimen_pending_carryover_is_not_complete(self):
        self.valid_records()
        self.write('shimen', 'done', 'delivery_verified',
                   {'attempts': 20, 'completed_count': 20, 'carryover_pending': 1})
        self.assert_rejected('shimen_not_verified_complete')

    def test_full_counts_without_done_status_are_rejected(self):
        for task, count, stage in (
            ('shimen', 20, 'delivery_verified'),
            ('zhuagui', 25, 'all_25_completed_gourds_unopened'),
        ):
            for status in ('running', 'paused', 'blocked'):
                with self.subTest(task=task, status=status):
                    self.valid_records()
                    self.write(task, status, stage, {'attempts': count, 'completed_count': count})
                    self.assert_rejected(f'{task}_not_verified_complete')

    def test_zhuagui_requires_exact_twenty_five_attempts_and_deliveries(self):
        self.valid_records()
        for attempts, completed in ((None, 25), (25, None), (24, 25), (25, 24),
                                    (26, 25), (25, 26), (25, 0)):
            with self.subTest(attempts=attempts, completed=completed):
                counters = {key: value for key, value in (
                    ('attempts', attempts), ('completed_count', completed)
                ) if value is not None}
                self.write('zhuagui', 'done', 'all_25_completed_gourds_unopened', counters)
                self.assert_rejected('zhuagui_not_verified_complete')

    def test_partial_zhuagui_target_does_not_unlock_rewards(self):
        self.valid_records()
        self.ctx.config.zhuagui_target = 10
        for status, stage in (
            ('paused', 'target_10_completed_gourds_unopened'),
            ('done', 'all_25_completed_gourds_unopened'),
        ):
            with self.subTest(status=status):
                self.write('zhuagui', status, stage, {'attempts': 10, 'completed_count': 10})
                self.assert_rejected('zhuagui_not_verified_complete')

    def test_zhuagui_needs_final_quota_verification_stage(self):
        self.valid_records()
        for stage in ('', 'one_task_completed', 'accept_reserved', 'completed_card_ledger_mismatch'):
            with self.subTest(stage=stage):
                self.write('zhuagui', 'done', stage, {'attempts': 25, 'completed_count': 25})
                self.assert_rejected('zhuagui_not_verified_complete')

    def test_each_dungeon_must_verify_reward_state(self):
        for task in ('wuji', 'chechi'):
            for stage in ('reward_claim_requested', 'in_progress', 'completion_detected', ''):
                with self.subTest(task=task, stage=stage):
                    self.valid_records()
                    self.write(task, 'done', stage)
                    self.assert_rejected(f'{task}_not_verified_complete')

    def test_verified_claimed_and_intentionally_unclaimed_dungeons_are_accepted(self):
        self.valid_records()
        for first in ('reward_claimed', 'reward_intentionally_unclaimed'):
            for second in ('reward_claimed', 'reward_intentionally_unclaimed'):
                with self.subTest(wuji=first, chechi=second):
                    self.write('wuji', 'done', first)
                    self.write('chechi', 'done', second)
                    self.assertIs(self.task.prerequisites(self.ctx), True)

    def test_dungeon_reward_stage_without_done_is_rejected(self):
        self.valid_records()
        for status in ('running', 'paused', 'blocked'):
            with self.subTest(status=status):
                self.write('wuji', status, 'reward_intentionally_unclaimed')
                self.assert_rejected('wuji_not_verified_complete')

    def test_all_configured_dungeons_are_required(self):
        self.valid_records()
        self.ctx.config.dungeons = self.lua.table_from(['wuji', 'chechi', 'custom'])
        self.assert_rejected('custom_not_verified_complete')
        self.write('custom', 'done', 'reward_claimed')
        self.assertIs(self.task.prerequisites(self.ctx), True)

    def test_unselected_dungeon_does_not_block_selected_dungeon(self):
        self.valid_records()
        self.ctx.config.dungeons = self.lua.table_from(['wuji'])
        self.write('chechi', 'running', 'reward_claim_requested')
        self.assertIs(self.task.prerequisites(self.ctx), True)

    def test_missing_dungeon_configuration_uses_both_default_dungeons(self):
        self.valid_records()
        self.ctx.config.dungeons = None
        self.write('chechi', 'done', 'reward_claim_requested')
        self.assert_rejected('chechi_not_verified_complete')

    def test_previous_business_day_ledgers_cannot_unlock_current_day(self):
        self.valid_records(date='20261013')
        self.assert_rejected('shimen_not_verified_complete')
        self.assertEqual(self.progress.read(self.ctx, 'shimen', '20261013')['completed_count'], 20)
        self.assertIsNone(self.progress.read(self.ctx, 'shimen'))

    def test_current_shimen_cannot_use_previous_day_zhuagui_or_dungeons(self):
        self.valid_records(date='20261013')
        self.write('shimen', 'done', 'delivery_verified', {'attempts': 20, 'completed_count': 20})
        self.assert_rejected('zhuagui_not_verified_complete')
        self.write('zhuagui', 'done', 'all_25_completed_gourds_unopened',
                   {'attempts': 25, 'completed_count': 25})
        self.assert_rejected('wuji_not_verified_complete')

    def test_another_role_complete_ledgers_cannot_unlock_selected_role(self):
        self.valid_records(ctx=self.lua.globals().other)
        self.assert_rejected('shimen_not_verified_complete')
        self.valid_records()
        self.write('zhuagui', 'running', 'accept_reserved',
                   {'attempts': 1, 'completed_count': 0}, ctx=self.lua.globals().other)
        self.assertIs(self.task.prerequisites(self.ctx), True)
        self.assertEqual(self.progress.read(self.ctx, 'zhuagui')['completed_count'], 25)

    def test_shimen_verified_done_is_skipped_for_daily_and_complete(self):
        task = self.lua.eval("require('tasks.shimen.task')")[0]
        for step in ('daily', 'complete'):
            for stage in ('delivery_verified', 'completion_card_verified', 'one_task_completed'):
                with self.subTest(step=step, stage=stage):
                    self.ctx.config.step = step
                    self.write('shimen', 'done', stage, {'attempts': 20, 'completed_count': 20})
                    result = task.run(self.ctx)
                    self.assertEqual((result['status'], result['reason']), ('done', 'daily_done_skip'))
                    self.assertEqual(len(self.lua.globals().taps), 0)
                    self.assertEqual(len(self.lua.globals().captures), 0)
                    self.assertEqual(self.lua.globals().page_reads, 0)

    def test_shimen_unverified_identity_cannot_skip_done_ledger(self):
        task = self.lua.eval("require('tasks.shimen.task')")[0]
        self.write('shimen', 'done', 'delivery_verified', {'attempts': 20, 'completed_count': 20})
        self.ctx.identity_verified = False
        for step in ('daily', 'complete'):
            with self.subTest(step=step):
                self.ctx.config.step = step
                result = task.run(self.ctx)
                self.assertEqual((result['status'], result['reason']),
                                 ('blocked', 'shimen_active_task_ownership_missing'))
                self.assertEqual(len(self.lua.globals().taps), 0)

    def test_shimen_unverified_or_incomplete_done_ledger_cannot_skip(self):
        task = self.lua.eval("require('tasks.shimen.task')")[0]
        for stage, attempts, completed, carryover in (
            ('accept_reserved', 20, 20, 0),
            ('delivery_verified', 19, 20, 0),
            ('delivery_verified', 20, 19, 0),
            ('delivery_verified', 20, 20, 1),
        ):
            with self.subTest(stage=stage, attempts=attempts, completed=completed, carryover=carryover):
                self.write('shimen', 'done', stage, {'attempts': attempts,
                           'completed_count': completed, 'carryover_pending': carryover})
                result = task.run(self.ctx)
                self.assertEqual((result['status'], result['reason']),
                                 ('blocked', 'shimen_active_task_ownership_missing'))
                self.assertEqual(len(self.lua.globals().taps), 0)

    def test_shimen_previous_day_or_other_role_done_cannot_skip_current_role(self):
        task = self.lua.eval("require('tasks.shimen.task')")[0]
        self.write('shimen', 'done', 'delivery_verified',
                   {'attempts': 20, 'completed_count': 20}, date='20261013')
        self.write('shimen', 'done', 'delivery_verified',
                   {'attempts': 20, 'completed_count': 20}, ctx=self.lua.globals().other)
        result = task.run(self.ctx)
        self.assertEqual((result['status'], result['reason']),
                         ('blocked', 'shimen_active_task_ownership_missing'))
        self.assertEqual(len(self.lua.globals().taps), 0)


class ScreenCaptureInitializationTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            calls={}
            init=function(direction) table.insert(calls,'init:'..direction) end
            getScreenSize=function() return 1080,1920 end
        ''')
        self.screen = self.lua.eval("require('common.screen')")[0]

    def test_first_init_resets_capture_before_initialization_and_later_calls_do_not(self):
        self.lua.execute("resetScreen=function() table.insert(calls,'reset') end")
        self.screen.init(1)
        self.assertEqual(list(self.lua.globals().calls.values()), ['reset', 'init:1'])
        self.assertEqual(self.screen.size(), (1920, 1080))
        self.screen.init(2)
        self.screen.init(0)
        self.assertEqual(list(self.lua.globals().calls.values()),
                         ['reset', 'init:1', 'init:2', 'init:0'])
        self.assertEqual(self.screen.size(), (1080, 1920))

    def test_init_without_reset_api_retains_initialization_and_coordinate_size(self):
        for direction, size in ((0, (1080, 1920)), (1, (1920, 1080)),
                                (2, (1920, 1080)), (0, (1080, 1920))):
            with self.subTest(direction=direction):
                self.screen.init(direction)
                self.assertEqual(self.screen.size(), size)
        self.assertEqual(list(self.lua.globals().calls.values()),
                         ['init:0', 'init:1', 'init:2', 'init:0'])


if __name__ == '__main__':
    unittest.main()
