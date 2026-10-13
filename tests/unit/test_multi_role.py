"""Selected-task completion must cover every independently verified role."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class MultiRoleTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            events={}; visits={}; calls={}; roster=true; home=true
            ctx={config={accounts={{alias='first',claim_dungeon_rewards=true},{alias='second',claim_dungeon_rewards=false}},tasks={'zhuagui','dungeon'}}}
            package.preload['dfx.log']=function() return {write=function(c,e,d) events[#events+1]={e,d} end} end
            package.preload['dfx.snapshot']=function() return {capture=function() end} end
            package.preload['common.navigation']=function() return {
                verify_roster=function() return roster end,
                prepare_recorded=function(c)
                    visits[#visits+1]=c.account.alias
                    c.identity_verified=c.account.alias~=bad_identity
                    return c.identity_verified
                end,
                finish_account=function() return home end
            } end
            for _,name in ipairs({'zhuagui','dungeon'}) do
                local task=name
                package.preload['tasks.'..name..'.task']=function() return {run=function(c)
                    assert(c.identity_verified)
                    calls[#calls+1]={c.account.alias,task,c.account.claim_dungeon_rewards}
                    return {status=c.account.alias==failed_role and 'paused' or 'done',reason='fixture'}
                end} end
            end
        ''')

    def run_daily(self):
        module=self.lua.eval("require('daily')")
        if isinstance(module,tuple): module=module[0]
        module.run(self.lua.globals().ctx)
        return [(v[1],v[2]) for v in self.lua.globals().events.values()]

    def test_all_roles_are_verified_and_policies_remain_separate(self):
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first','second'])
        calls=list(self.lua.globals().calls.values())
        self.assertEqual([(c[1],c[2],c[3]) for c in calls],
                         [('first','zhuagui',True),('first','dungeon',True),('second','zhuagui',False),('second','dungeon',False)])
        self.assertIn(('summary','scope=roles roles_expected=2 roles_completed=2 all_roles_done=true selected_done=true daily_done=false'),events)

    def test_paused_task_stops_run_without_claiming_other_roles_done(self):
        self.lua.execute("failed_role='first'")
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first'])
        self.assertTrue(any('all_roles_done=false' in detail for event,detail in events if event=='summary'))

    def test_configured_role_subset_and_task_subset_are_respected(self):
        self.lua.execute("ctx.config.accounts[3]={alias='third'};ctx.config.selected_accounts={'first','third'};ctx.config.tasks={'dungeon'}")
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first','third'])
        self.assertEqual([(c[1],c[2]) for c in self.lua.globals().calls.values()],[('first','dungeon'),('third','dungeon')])
        self.assertIn(('summary','scope=selected_roles roles_expected=2 roles_completed=2 all_roles_done=false selected_done=true daily_done=false'),events)

    def test_unconfigured_selection_has_no_task_actions(self):
        self.lua.execute("ctx.config.selected_accounts={'missing'}")
        with self.assertRaises(Exception):self.run_daily()
        self.assertEqual(len(self.lua.globals().calls),0)

    def test_selected_regression_checks_roster_but_only_runs_requested_role(self):
        self.lua.execute("ctx.config.selected_account='second'")
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['second'])
        self.assertIn(('summary','scope=selected_roles roles_expected=1 roles_completed=1 all_roles_done=false selected_done=true daily_done=false'),events)
        self.lua.execute('roster=false; calls={}')
        self.run_daily()
        self.assertEqual(len(self.lua.globals().calls),0)

    def test_wrong_identity_has_no_task_actions_and_next_role_is_attempted(self):
        self.lua.execute("bad_identity='first'")
        self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first','second'])
        self.assertEqual([c[1] for c in self.lua.globals().calls.values()],['second','second'])

    def test_unconfigured_roster_blocks_all_paid_actions(self):
        self.lua.execute('roster=false')
        events=self.run_daily()
        self.assertEqual(len(self.lua.globals().calls),0)
        self.assertTrue(any('saved_roster_not_verified' in detail for _,detail in events))

    def test_unsafe_scene_prevents_switch_and_does_not_report_success(self):
        self.lua.execute('home=false')
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first'])
        self.assertIn(('summary','all_roles_done=false selected_done=false daily_done=false reason=return_home_not_verified'),events)


if __name__=='__main__': unittest.main()
