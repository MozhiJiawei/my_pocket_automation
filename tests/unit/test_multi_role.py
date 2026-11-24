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
            package.preload['tasks.dungeon.pages']=function() return {state=function() return receipt_state or 'unknown' end} end
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
            for _,name in ipairs({'shimen','zhuagui','dungeon','rewards'}) do
                local task=name
                package.preload['tasks.'..name..'.task']=function() return {run=function(c)
                    assert(c.identity_verified)
                    calls[#calls+1]={c.account.alias,task,c.account.claim_dungeon_rewards}
                    return {status=c.account.alias==failed_role and (incomplete_status or 'paused') or 'done',reason='fixture'}
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

    def receipt_without_task_audit(self,switched=False,date=None):
        self.lua.execute('''
            receipt_state='wuji_claim_receipt';ctx.config.business_date=os.date('%Y%m%d')
            require('common.navigation').verify_roster=function(c)
                c.account=c.config.accounts[1];c.identity_verified=true;c.role_switched=switched
                return true
            end
        ''')
        self.lua.globals().switched=switched
        if date:self.lua.globals().ctx.config.business_date=date
        self.run_daily()
        self.lua.globals().ctx.account=self.lua.globals().ctx.config.accounts[1]
        return self.lua.eval("require('progress').read(ctx,'wuji')")

    def test_roster_verification_cannot_credit_a_receipt_before_task_audit(self):
        self.assertIsNone(self.receipt_without_task_audit())
        self.lua.globals().ctx.account=self.lua.globals().ctx.config.accounts[2]
        self.assertIsNone(self.lua.eval("require('progress').read(ctx,'wuji')"))

    def test_switching_role_does_not_copy_the_previous_roles_receipt(self):
        self.assertIsNone(self.receipt_without_task_audit(switched=True))

    def test_receipt_cannot_cross_the_business_day(self):
        self.assertIsNone(self.receipt_without_task_audit(date='19000101'))

    def test_daily_modules_run_in_fixed_order_per_verified_role(self):
        self.lua.execute("ctx.config.tasks={'rewards','dungeon','zhuagui','shimen'}")
        events=self.run_daily()
        self.assertEqual([(c[1],c[2]) for c in self.lua.globals().calls.values()],
                         [(alias,task) for alias in ('first','second') for task in ('shimen','zhuagui','dungeon','rewards')])
        self.assertIn(('summary','scope=roles roles_expected=2 roles_completed=2 all_roles_done=true selected_done=true daily_done=true'),events)

    def configure_automatic_dungeons(self):
        self.lua.execute('''
            ctx.config.step='daily';ctx.config.automatic_dungeons=true
            ctx.config.business_date=os.date('%Y%m%d');ctx.config.tasks={'zhuagui','dungeon','rewards'}
            checked={};counts={};targets={};saved={}
            package.preload['tasks.rewards.inventory']=function() return {ghost_count=function(c)
                assert(checked[c.account.alias]);counts[#counts+1]=c.account.alias
                if missing==c.account.alias then return nil,'ghost_gourd_count_not_verified' end
                return c.account.alias=='first' and 3 or 2
            end} end
            package.preload['completion']=function() return {
                read=function(c,id) return saved[c.account.alias..':'..id] end,
                write=function(c,id,status,stage)
                    assert(stage=='selected_dungeons_verified');saved[c.account.alias..':'..id]={status=status,stage=stage}
                end
            } end
            local scope=require('tasks.dungeon.scope')
            package.preload['tasks.rewards.task']=function() return {
                verify_task_completed=function(c,task)
                    assert(task=='zhuagui' and c.identity_verified);checked[c.account.alias]=true;return true
                end,
                run=function(c)
                    assert(scope.completed(c));return {status='done',reason='fixture'}
                end
            } end
            package.preload['tasks.dungeon.task']=function() return {run=function(c)
                local names,reason=scope.resolve(c)
                if not names then return {status='blocked',reason=reason} end
                assert(scope.resolve(c)==names)
                targets[c.account.alias]=table.concat(names,',')
                return {status='done',reason='fixture'}
            end} end
        ''')

    def test_automatic_dungeons_use_each_roles_count_and_reuse_only_verified_scope(self):
        self.configure_automatic_dungeons()
        self.run_daily()
        self.assertEqual(self.lua.globals().targets['first'],'wuji,heifeng,shuilu,chechi')
        self.assertEqual(self.lua.globals().targets['second'],'wuji,heifeng,shuilu,chechi,pingding')
        self.lua.execute("targets={};missing='first'")
        self.run_daily()
        self.assertEqual(list(self.lua.globals().counts.values()),['first','second'])
        self.assertEqual(list(self.lua.globals().targets.values()),[])

    def test_unknown_ghost_gourd_count_stops_before_rewards_and_other_roles(self):
        self.configure_automatic_dungeons()
        self.lua.execute("missing='first'")
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().counts.values()),['first'])
        self.assertEqual(list(self.lua.globals().saved.values()),[])
        self.assertIn(('task_result','dungeon status=blocked reason=ghost_gourd_count_not_verified'),events)

    def test_explicit_rewards_scope_does_not_reuse_an_unrelated_automatic_clear(self):
        self.lua.execute('''
            ctx.config.step='daily';ctx.config.tasks={'rewards'};ctx.config.dungeons={'pingding'}
            ctx.config.selected_accounts={'first'}
            package.preload['completion']=function() return {read=function(c,id)
                if id=='rewards' or id=='dungeonsclaimed' then return {status='done'} end
            end} end
        ''')
        self.run_daily()
        self.assertEqual([(c[1],c[2]) for c in self.lua.globals().calls.values()],[('first','rewards')])

    def test_five_roles_resume_completed_tasks_after_identity_checks(self):
        self.lua.execute('''
            ctx.config.tasks={'shimen','zhuagui','dungeon','rewards'}
            for i=3,5 do ctx.config.accounts[i]={alias='role'..i} end
            package.preload['completion']=function() return {
                read=function(c,task)
                    assert(c.identity_verified)
                    if task=='shimen' and c.account.alias~='second' then return {status='done'} end
                end
            } end
        ''')
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first','second','role3','role4','role5'])
        self.assertEqual(len(list(self.lua.globals().calls.values())),16)
        self.assertIn(('summary','scope=roles roles_expected=5 roles_completed=5 all_roles_done=true selected_done=true daily_done=true'),events)

    def test_selected_modules_keep_fixed_order_without_adding_missing_tasks(self):
        self.lua.execute("ctx.config.tasks={'rewards','shimen'};ctx.config.selected_accounts={'second'}")
        events=self.run_daily()
        self.assertEqual([(c[1],c[2]) for c in self.lua.globals().calls.values()],[('second','shimen'),('second','rewards')])
        self.assertIn(('summary','scope=selected_roles roles_expected=1 roles_completed=1 all_roles_done=false selected_done=true daily_done=false'),events)

    def test_prior_task_pause_stops_before_rewards_even_if_requested_first(self):
        self.lua.execute("ctx.config.tasks={'rewards','shimen','dungeon','zhuagui'};failed_role='first'")
        events=self.run_daily()
        self.assertEqual([(c[1],c[2]) for c in self.lua.globals().calls.values()],[('first','shimen')])
        self.assertIn(('summary','all_roles_done=false selected_done=false daily_done=false reason=shimen_paused'),events)

    def test_paused_task_stops_run_without_claiming_other_roles_done(self):
        self.lua.execute("failed_role='first'")
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first'])
        self.assertTrue(any('all_roles_done=false' in detail for event,detail in events if event=='summary'))

    def test_returned_failure_evidence_prevents_a_duplicate_outer_capture(self):
        self.lua.execute('''
            captures={}
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                captures[#captures+1]=label;return label..'.png' end} end
            package.preload['tasks.zhuagui.task']=function() return {run=function(c)
                return {status='paused',reason='find_icon_not_found',
                    failure_evidence=require('dfx.snapshot').capture(c,'find_icon_not_found')}
            end} end
        ''')
        events=self.run_daily()
        self.assertEqual(list(self.lua.globals().captures.values()),['find_icon_not_found'])
        self.assertIn(('task_result','zhuagui status=paused reason=find_icon_not_found'),events)
        self.assertFalse(any(event=='account_result' for event,_ in events))

    def test_missing_task_failure_evidence_still_gets_an_outer_capture(self):
        self.lua.execute('''
            captures={};failed_role='first'
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                captures[#captures+1]=label end} end
        ''')
        self.run_daily()
        self.assertEqual(list(self.lua.globals().captures.values()),['task_zhuagui_incomplete'])

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

    def test_wrong_identity_stops_before_switching_to_another_role(self):
        self.lua.execute("bad_identity='first'")
        self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first'])
        self.assertEqual(len(self.lua.globals().calls),0)

    def test_running_task_cannot_start_next_task_or_role(self):
        self.lua.execute("failed_role='first';incomplete_status='running'")
        self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first'])
        self.assertEqual([(c[1],c[2]) for c in self.lua.globals().calls.values()],[('first','zhuagui')])

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

    def test_failed_return_home_stops_even_if_a_later_attempt_would_succeed(self):
        self.lua.execute('''
            finishes=0
            require('common.navigation').finish_account=function()
                finishes=finishes+1
                return finishes>1
            end
        ''')
        self.run_daily()
        self.assertEqual(list(self.lua.globals().visits.values()),['first'])
        self.assertEqual(self.lua.globals().finishes,1)


if __name__=='__main__': unittest.main()
