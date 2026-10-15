"""Reward prerequisites audit the game, independent of previous task records."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

class RewardsGuardTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute("""
            os.date=function() return '20261014' end
            ctx={config={business_date='20261014',step='complete',dungeons={'wuji','chechi'}},account={alias='first'},identity_verified=true}
            state='home';current=nil;taps={};captures={};swipes=0;verified={};after_scroll={};audits={}
            keepScreen=function() end;mSleep=function() end
            getColor=function() return swipes*0x001010 end
            io.open=function() error('task state must not touch disk') end
            loadfile=function() error('task state must not load disk') end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function(c,label) captures[#captures+1]=label end} end
            package.preload['tasks.rewards.pages']=function() return {state=function() return state end} end
            package.preload['tasks.zhuagui.assets.home_tasks']=function() return 'home_tasks' end
            package.preload['tasks.shimen.pages']=function() return {
                features={task_list='list',completed_card='shimen_completed'},actions={},state=function() return state end} end
            package.preload['tasks.zhuagui.pages']=function() return {
                features={task_list_title='list',completed_card='zhuagui_completed'}} end
            package.preload['common.detector']=function() return {present=function(f)
                if f=='list' then return state=='task_list' end
                local task=type(f)=='string' and f:match('^(%w+)_completed$')
                return task and current==task and state=='task_list' and verified[task]==true and swipes>=(after_scroll[task] or 0)
            end} end
            package.preload['common.device']=function() return {
                tap=function(c,f,label)
                    assert(f=='home_tasks' and state=='home');taps[#taps+1]=label
                    current=label:match('^rewards_verify_(%w+)$');assert(current)
                    state=entry_state or 'task_list';return true
                end,
                wait=function(predicate) return predicate() end,
                swipe=function()
                    swipes=swipes+1
                    if leave_list then state='unknown' end
                    return true
                end} end
            package.preload['common.navigation']=function() return {
                return_home=function() if home_failed then return false end;state='home';return true end} end
            package.preload['tasks.dungeon.task']=function() return {verify_completed=function(c,id)
                assert(state=='home');audits[#audits+1]=id
                return verified[id]==true
            end} end
        """)
        self.ctx=self.lua.globals().ctx
        self.task=self.lua.eval("require('tasks.rewards.task')")[0]
        self.progress=self.lua.eval("(require('progress'))")

    def complete_pages(self):
        self.lua.execute("verified={shimen=true,zhuagui=true,wuji=true,chechi=true}")

    def assert_rejected(self, reason):
        self.assertEqual(self.task.prerequisites(self.ctx),(False,reason))

    def test_missing_all_completed_pages_is_rejected(self):
        self.assert_rejected('shimen_not_verified_complete')
        self.assertEqual(self.lua.globals().swipes,24)

    def test_each_missing_required_page_is_rejected(self):
        for task in ('shimen','zhuagui','wuji','chechi'):
            with self.subTest(task=task):
                self.setUp();self.complete_pages();self.lua.globals().verified[task]=False
                self.assert_rejected(task+'_not_verified_complete')

    def test_verified_game_pages_are_accepted_without_task_records(self):
        self.complete_pages()
        self.assertIs(self.task.prerequisites(self.ctx),True)
        self.assertEqual(self.progress.read(self.ctx,'shimen')['stage'],'completion_card_verified')
        self.assertEqual(list(self.lua.globals().audits.values()),['wuji','chechi'])

    def test_shimen_completion_does_not_require_numeric_task_fields(self):
        self.complete_pages()
        self.progress.write(self.ctx,'shimen','running','delivery',self.lua.table_from({'attempts':0}))
        self.assertIs(self.task.prerequisites(self.ctx),True)

    def test_audit_does_not_invent_accept_or_fee_history(self):
        self.complete_pages();self.task.prerequisites(self.ctx)
        self.assertEqual(list(self.lua.globals().taps.values()),['rewards_verify_shimen','rewards_verify_zhuagui'])
        self.assertEqual(self.progress.read(self.ctx,'shimen')['stage'],'completion_card_verified')

    def test_runtime_done_cannot_replace_a_missing_shimen_card(self):
        self.progress.write(self.ctx,'shimen','done','delivery_verified')
        self.assert_rejected('shimen_not_verified_complete')

    def test_active_shimen_page_is_not_a_completed_card(self):
        self.complete_pages();self.lua.execute("entry_state='go'")
        self.assert_rejected('shimen_not_verified_complete')
        self.assertEqual(self.lua.globals().swipes,0)

    def test_numeric_counts_cannot_unlock_rewards(self):
        for task in ('shimen','zhuagui'):
            self.progress.write(self.ctx,task,'done','counts_only',self.lua.table_from({'completed_count':25}))
        self.assert_rejected('shimen_not_verified_complete')

    def test_zhuagui_completion_does_not_require_numeric_fields(self):
        self.complete_pages()
        self.progress.write(self.ctx,'zhuagui','running','start_requested',self.lua.table_from({'attempts':1}))
        self.assertIs(self.task.prerequisites(self.ctx),True)

    def test_partial_zhuagui_does_not_unlock_rewards(self):
        self.complete_pages();self.lua.globals().verified.zhuagui=False
        self.progress.write(self.ctx,'zhuagui','done','one_task_completed')
        self.assert_rejected('zhuagui_not_verified_complete')

    def test_verified_runtime_zhuagui_does_not_repeat_card_search(self):
        self.complete_pages();self.lua.globals().verified.zhuagui=False
        self.progress.write(self.ctx,'zhuagui','done','completion_card_verified')
        self.assertIs(self.task.prerequisites(self.ctx),True)
        self.assertEqual(list(self.lua.globals().taps.values()),['rewards_verify_shimen'])

    def test_each_dungeon_requires_a_fresh_audit(self):
        for task in ('wuji','chechi'):
            self.setUp();self.complete_pages();self.lua.globals().verified[task]=False
            self.progress.write(self.ctx,task,'done','reward_claim_requested')
            self.assert_rejected(task+'_not_verified_complete')

    def test_dungeon_audit_uses_pages_instead_of_claim_history(self):
        self.complete_pages()
        for task in ('wuji','chechi'):self.progress.write(self.ctx,task,'paused','reward_claim_requested')
        self.assertIs(self.task.prerequisites(self.ctx),True)

    def test_running_dungeon_page_is_not_completion(self):
        self.complete_pages();self.lua.globals().verified.wuji=False
        self.assert_rejected('wuji_not_verified_complete')

    def test_every_configured_dungeon_is_checked(self):
        self.complete_pages();self.ctx.config.dungeons=self.lua.table_from(['chechi','wuji'])
        self.assertIs(self.task.prerequisites(self.ctx),True)
        self.assertEqual(list(self.lua.globals().audits.values()),['chechi','wuji'])

    def test_unselected_dungeon_does_not_block_selected_dungeon(self):
        self.complete_pages();self.ctx.config.dungeons=self.lua.table_from(['wuji'])
        self.lua.globals().verified.chechi=False
        self.assertIs(self.task.prerequisites(self.ctx),True)
        self.assertEqual(list(self.lua.globals().audits.values()),['wuji'])

    def test_default_configuration_checks_both_dungeons(self):
        self.complete_pages();self.ctx.config.dungeons=None;self.lua.globals().verified.chechi=False
        self.assert_rejected('chechi_not_verified_complete')

    def test_previous_business_day_cannot_unlock_rewards(self):
        self.complete_pages();self.ctx.config.business_date='20261013'
        self.assert_rejected('rewards_business_date_not_verified')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_completed_cards_below_the_fold_use_shared_scrolling(self):
        self.complete_pages();self.lua.execute('after_scroll.shimen=2;after_scroll.zhuagui=4')
        self.assertIs(self.task.prerequisites(self.ctx),True)
        self.assertEqual(self.lua.globals().swipes,4)

    def test_another_role_state_does_not_unlock_selected_role(self):
        other=self.lua.table_from({'account':self.lua.table_from({'alias':'other'})})
        self.progress.write(other,'shimen','done','delivery_verified')
        self.assert_rejected('shimen_not_verified_complete')

    def test_shimen_done_record_does_not_skip_game_verification(self):
        task=self.lua.eval("require('tasks.shimen.task')")[0]
        self.progress.write(self.ctx,'shimen','done','completion_card_verified')
        self.lua.execute("state='unknown'")
        self.assertEqual(task.run(self.ctx)['reason'],'shimen_task_page_not_verified')

    def test_identity_must_be_verified_before_audits(self):
        self.complete_pages();self.ctx.identity_verified=False
        self.assert_rejected('rewards_identity_not_verified')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_page_change_during_card_search_stops_audit(self):
        self.complete_pages();self.lua.execute('after_scroll.shimen=3;leave_list=true')
        self.assert_rejected('shimen_not_verified_complete')
        self.assertEqual(self.lua.globals().swipes,1)
        self.assertEqual(len(self.lua.globals().audits),0)

    def test_return_home_failure_stops_later_audits(self):
        self.complete_pages();self.lua.execute('home_failed=true')
        self.assert_rejected('shimen_not_verified_complete')
        self.assertEqual(len(self.lua.globals().audits),0)


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
