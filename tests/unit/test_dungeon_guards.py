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
            package.preload['common.detector']=function() return {present=function() return false end} end
            package.preload['progress']=function() return {
                read=function(ctx,id) return records[id] end,
                write=function(ctx,id,status,stage) records[id]={status=status,stage=stage} end
            } end
            package.preload['tasks.dungeon.pages']=function() return {
                definitions={wuji={card={}},chechi={card={}}},
                state=function() return state end,
                features={start='start',overview_back='back',switch_wuji_chechi='switch'}
            } end
            package.preload['common.device']=function() return {
                tap=function(ctx,feature,label)
                    if feature=='start' then assert(records.wuji and records.wuji.status=='running') end
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

    def test_cannot_abandon_uncompleted_wuji(self):
        self.lua.execute("state='switch_wuji_chechi'; ctx.config.step='switch'; ctx.config.dungeon='chechi'")
        self.assertEqual(self.run_task()['status'], 'blocked')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_completion_only_clicks_back(self):
        self.lua.execute("state='wuji_reward_sealed'; ctx.config.step='finish'")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(list(self.lua.globals().taps.values()), ['back'])
        self.assertEqual(self.lua.globals().records['wuji']['stage'], 'reward_intentionally_unclaimed')

    def test_done_daily_tasks_skip_without_device_actions(self):
        self.lua.execute("ctx.config.step='daily'; records.wuji={status='done'}; records.chechi={status='done'}")
        self.assertEqual(self.run_task()['status'], 'done')
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_unknown_resume_is_bounded_without_clicking(self):
        self.lua.execute("records.wuji={status='running'}")
        self.assertEqual(self.run_task()['status'], 'paused')
        self.assertLessEqual(self.lua.globals().clock, 31)
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
