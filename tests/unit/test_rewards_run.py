"""Real rewards.run gates and composes inventory clearing before completion."""
from pathlib import Path
import unittest

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class RewardsRunTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            os.date=function() return '20261014' end
            ctx={config={business_date='20261014',step='daily',task='rewards',
                dungeons={'wuji','chechi'}},identity_verified=true}
            records={}; writes={}; calls={}; clears={}; captures={}; outcomes={}
            page_state='home'; swipes=0; card_checks=0; prepare_calls=0
            package.preload['progress']=function() return {
                read=function(c,task)
                    assert(c==ctx);calls[#calls+1]='read:'..task
                    return records[task]
                end,
                write=function(c,task,status,stage,...)
                    assert(c==ctx);calls[#calls+1]='write:'..task
                    writes[#writes+1]={task=task,status=status,stage=stage,
                        extra_arguments=select('#',...)}
                    records[task]={status=status,stage=stage}
                end
            } end
            package.preload['tasks.rewards.pages']=function() return {
                features={task_tab='task_tab',treasury_tab='treasury_tab'},
                state=function() return page_state end,
                select_category=function() error('clearing belongs to inventory.clear') end
            } end
            package.preload['tasks.shimen.pages']=function() return {
                features={task_list='shimen_task_list',completed_card='shimen_completed_card'}
            } end
            package.preload['tasks.zhuagui.assets.home_tasks']=function() return 'home_tasks' end
            package.preload['common.assets.home_dungeon']=function() return {
                tap_offset={10,20}
            } end
            package.preload['common.detector']=function() return {
                present=function(feature)
                    if feature=='shimen_task_list' then return page_state=='shimen_list' end
                    if feature=='shimen_completed_card' then
                        card_checks=card_checks+1
                        return page_state=='shimen_list' and shimen_card_present and
                            swipes>=(card_after_swipes or 0)
                    end
                    if feature=='task_tab' then return page_state=='inventory' end
                    error('unexpected feature: '..tostring(feature))
                end
            } end
            package.preload['common.device']=function() return {
                tap=function(c,feature,label)
                    assert(c==ctx);calls[#calls+1]='tap:'..label
                    assert(page_state=='home', 'entry requires the home page')
                    if label=='rewards_verify_shimen' then
                        assert(feature=='home_tasks');page_state='shimen_list'
                    elseif label=='rewards_open_inventory' then
                        assert(feature.tap_offset[1]==126 and feature.tap_offset[2]==837)
                        page_state='inventory'
                    else error('unexpected tap: '..label) end
                    return true
                end,
                wait=function(predicate,attempts)
                    for _=1,attempts do if predicate() then return true end end
                    return false
                end,
                swipe=function(c,feature,label)
                    assert(c==ctx and page_state=='shimen_list')
                    assert(feature=='shimen_task_list' and label=='rewards_find_shimen_completed')
                    swipes=swipes+1;calls[#calls+1]='swipe:shimen'
                    return true
                end
            } end
            package.preload['common.navigation']=function() return {
                prepare_recorded=function(c)
                    assert(c==ctx);prepare_calls=prepare_calls+1
                    calls[#calls+1]='prepare_home'
                    if not c.identity_verified or (prepare_calls>1 and return_home_failed) then
                        return false
                    end
                    page_state='home';return true
                end,
                return_home=function(c)
                    assert(c==ctx and page_state=='shimen_list')
                    calls[#calls+1]='return_home';page_state='home';return true
                end
            } end
            package.preload['tasks.rewards.inventory']=function() return {
                clear=function(c,category)
                    assert(c==ctx and page_state=='inventory')
                    clears[#clears+1]=category;calls[#calls+1]='clear:'..category
                    return outcomes[category] or {status='done',reason='category_empty'}
                end
            } end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {
                capture=function(c,reason) assert(c==ctx);captures[#captures+1]=reason end
            } end
        ''')
        self.task = self.lua.eval("require('tasks.rewards.task')")[0]
        self.globals = self.lua.globals()
        self.ctx = self.globals.ctx

    def valid_records(self):
        self.lua.execute('''
            records={
                shimen={status='done',stage='delivery_verified',attempts=20,completed_count=20},
                zhuagui={status='done',stage='all_25_completed_gourds_unopened',
                    attempts=25,completed_count=25},
                wuji={status='done',stage='reward_intentionally_unclaimed'},
                chechi={status='done',stage='reward_claimed'}
            }
        ''')

    def run_task(self):
        return self.task.run(self.ctx)

    def assert_result(self, result, status, reason):
        self.assertEqual((result['status'], result['reason']), (status, reason))

    def assert_no_clear_or_write(self):
        self.assertEqual(list(self.globals.clears.values()), [])
        self.assertEqual(list(self.globals.writes.values()), [])

    def assert_completion_write(self, stage):
        self.assertEqual(len(self.globals.writes), 1)
        self.assertEqual(dict(self.globals.writes[1]), {
            'task': 'rewards', 'status': 'done', 'stage': stage, 'extra_arguments': 0,
        })
        self.assertEqual(self.globals.page_state, 'home')

    def test_daily_clears_all_categories_then_returns_home_and_writes_only_completion(self):
        self.valid_records()
        result = self.run_task()
        self.assert_result(result, 'done', 'daily_inventory_empty')
        self.assertEqual(list(self.globals.calls.values()), [
            'prepare_home', 'read:shimen', 'read:zhuagui', 'read:wuji', 'read:chechi',
            'tap:rewards_open_inventory', 'clear:task', 'clear:dungeon', 'clear:special',
            'prepare_home', 'write:rewards',
        ])
        self.assert_completion_write('daily_inventory_empty')
        self.assertEqual(set(self.globals.records), {'shimen', 'zhuagui', 'wuji', 'chechi', 'rewards'})

    def test_each_missing_prerequisite_blocks_before_inventory_entry(self):
        for task in ('shimen', 'zhuagui', 'wuji', 'chechi'):
            with self.subTest(task=task):
                self.setUp()
                self.valid_records()
                self.globals.records[task] = None
                self.assert_result(self.run_task(), 'blocked', f'{task}_not_verified_complete')
                self.assert_no_clear_or_write()
                self.assertEqual(self.globals.page_state, 'home')
                self.assertFalse(any(call.startswith('tap:') for call in self.globals.calls.values()))

    def test_unverified_identity_blocks_before_any_category(self):
        self.valid_records()
        self.ctx.identity_verified = False
        self.assert_result(self.run_task(), 'blocked', 'rewards_identity_not_verified')
        self.assert_no_clear_or_write()
        self.assertEqual(list(self.globals.calls.values()), ['prepare_home'])

    def test_debug_matches_shimen_completed_card_and_writes_no_task_completion(self):
        self.ctx.config.step = 'complete'
        self.ctx.config.rewards_debug_after_shimen = True
        self.globals.shimen_card_present = True
        self.globals.card_after_swipes = 2
        self.assert_result(self.run_task(), 'done', 'debug_inventory_empty')
        self.assertEqual(self.globals.swipes, 2)
        self.assertEqual(self.globals.card_checks, 3)
        self.assertIn('rewards_shimen_completed', self.globals.captures.values())
        self.assertEqual(list(self.globals.clears.values()), ['task', 'dungeon', 'special'])
        self.assertEqual(list(self.globals.calls.values()), [
            'prepare_home', 'tap:rewards_verify_shimen', 'swipe:shimen', 'swipe:shimen',
            'return_home', 'tap:rewards_open_inventory', 'clear:task', 'clear:dungeon',
            'clear:special', 'prepare_home', 'write:rewards',
        ])
        self.assert_completion_write('debug_inventory_empty')
        self.assertEqual(set(self.globals.records), {'rewards'})

    def test_debug_missing_completed_card_stops_after_four_swipes_without_clearing(self):
        self.valid_records()
        self.ctx.config.step = 'complete'
        self.ctx.config.rewards_debug_after_shimen = True
        self.globals.shimen_card_present = False
        self.assert_result(self.run_task(), 'blocked', 'rewards_shimen_completed_card_not_verified')
        self.assertEqual(self.globals.swipes, 4)
        self.assertEqual(self.globals.card_checks, 5)
        self.assert_no_clear_or_write()
        self.assertNotIn('tap:rewards_open_inventory', self.globals.calls.values())

    def test_debug_daily_cannot_bypass_prerequisites(self):
        self.ctx.config.rewards_debug_after_shimen = True
        self.globals.shimen_card_present = True
        self.assert_result(self.run_task(), 'blocked', 'rewards_debug_scope_invalid')
        self.assert_no_clear_or_write()
        self.assertEqual(list(self.globals.calls.values()), ['prepare_home'])
        self.assertEqual(self.globals.card_checks, 0)

    def test_paused_category_stops_later_categories_and_completion(self):
        categories = ['task', 'dungeon', 'special']
        for index, category in enumerate(categories):
            with self.subTest(category=category):
                self.setUp()
                self.valid_records()
                self.globals.outcomes[category] = self.lua.table_from({
                    'status': 'paused', 'reason': 'rewards_action_result_not_verified',
                })
                self.assert_result(self.run_task(), 'paused', 'rewards_action_result_not_verified')
                self.assertEqual(list(self.globals.clears.values()), categories[:index + 1])
                self.assertEqual(len(self.globals.writes), 0)
                self.assertEqual(self.globals.prepare_calls, 1)
                self.assertNotIn('rewards', self.globals.records)

    def test_return_home_failure_after_all_categories_does_not_write_done(self):
        self.valid_records()
        self.globals.return_home_failed = True
        self.assert_result(self.run_task(), 'paused', 'rewards_return_home_not_verified')
        self.assertEqual(list(self.globals.clears.values()), ['task', 'dungeon', 'special'])
        self.assertEqual(self.globals.prepare_calls, 2)
        self.assertEqual(len(self.globals.writes), 0)
        self.assertNotIn('rewards', self.globals.records)


if __name__ == '__main__':
    unittest.main()
