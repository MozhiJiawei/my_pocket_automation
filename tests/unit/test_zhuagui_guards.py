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
            ctx={config={step='start',allow_reward_claim=false,zhuagui_budget=0},account={alias='fake'}}
            package.preload['tasks.zhuagui.pages']=function() return {
                state=function() return state end,
                features={rules='rules',cancel='cancel',home_tasks='home_tasks',task_card='task_card',accept='accept'}
            } end
            package.preload['common.assets.home_tab']=function() return 'home_tab' end
            package.preload['tasks.zhuagui.counter']=function() return {read=function()
                if missing_count then return nil end
                if visible_count~=nil then return visible_count end
                return record and record.attempts or 0
            end} end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function() end} end
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
                    for _,k in ipairs({'attempts','reserved_energy','completed_count'}) do
                        if counters and counters[k]~=nil then record[k]=counters[k] end
                    end
                end
            } end
            package.preload['common.device']=function() return {
                wait=function(predicate) return predicate() end,
                tap=function(c,feature,label)
                    table.insert(taps,feature)
                    if feature=='rules' then state='ready_cost_three'
                    elseif feature=='cancel' then state='task_list'
                    elseif feature=='home_tab' then state='home'
                    elseif feature=='home_tasks' then state=home_entry_state or 'task_list'
                    elseif feature=='task_card' then state='ready_cost_three'
                    elseif feature=='accept' then
                        assert(c.identity_verified,'identity required before paid task')
                        assert(record.status=='running' and record.reserved_energy==3,'reserve before accepting')
                        state='active_uncalibrated'
                    end
                    return true
                end
            } end
        ''')
        self.task = self.lua.eval("require('tasks.zhuagui.task')")[0]

    def run_task(self):
        return self.task.run(self.lua.globals().ctx)

    def assert_no_accept(self):
        self.assertNotIn('accept', list(self.lua.globals().taps.values()))

    def test_default_zero_cap_never_accepts(self):
        result = self.run_task()
        self.assertEqual(result['reason'], 'energy_budget_exhausted')
        self.assert_no_accept()
        self.assertIsNone(self.lua.globals().record)

    def test_entry_only_returns_home_verifies_identity_and_does_not_accept(self):
        self.lua.execute("ctx.config.step='enter'; state='rules'")
        result = self.run_task()
        self.assertEqual(result['status'], 'running')
        self.assertTrue(self.lua.globals().ctx['identity_verified'])
        self.assertEqual(list(self.lua.globals().taps.values()), ['rules','cancel','home_tab','home_tasks','task_card'])
        self.assert_no_accept()

    def test_reservation_precedes_single_accept(self):
        self.lua.execute('ctx.config.zhuagui_budget=3')
        self.assertEqual(self.run_task()['status'], 'running')
        self.assertEqual(self.lua.globals().record['reserved_energy'], 3)
        self.assertEqual(list(self.lua.globals().taps.values()).count('accept'), 1)

    def test_reserved_attempt_cannot_be_repeated(self):
        self.lua.execute("ctx.config.zhuagui_budget=15; record={status='running',reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'], 'active_attempt_already_reserved')
        self.assert_no_accept()

    def test_cap_survives_separate_invocations(self):
        self.lua.execute("ctx.config.zhuagui_budget=3; record={status='paused',reserved_energy=3,attempts=1}")
        self.assertEqual(self.run_task()['reason'], 'energy_budget_exhausted')
        self.assert_no_accept()

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

    def test_last_completion_finishes_without_accepting_26th_task(self):
        self.lua.execute("ctx.config.step='complete'; ctx.config.zhuagui_budget=75; record={status='running',attempts=25,completed_count=24,reserved_energy=75}")
        self.assertEqual(self.run_task()['status'],'done')
        self.assertEqual(self.lua.globals().record['completed_count'],25)
        self.assertEqual(self.lua.globals().record['status'],'done')
        self.assert_no_accept()

    def test_advance_records_one_completion_and_stops(self):
        self.lua.execute("ctx.config.step='advance'; record={status='running',attempts=1,completed_count=0,reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'],'one_task_completed')
        self.assertEqual(self.lua.globals().record['completed_count'],1)
        self.assert_no_accept()

    def test_reserved_but_unaccepted_task_is_not_completion(self):
        self.lua.execute("ctx.config.step='advance'; visible_count=0; record={status='running',attempts=1,completed_count=0,reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'],'completion_count_mismatch')
        self.assertEqual(self.lua.globals().record['completed_count'],0)
        self.assert_no_accept()

    def test_uncertain_count_never_records_completion(self):
        self.lua.execute("ctx.config.step='advance'; missing_count=true; record={status='running',attempts=1,completed_count=0,reserved_energy=3}")
        self.assertEqual(self.run_task()['reason'],'count_requires_calibration')
        self.assertEqual(self.lua.globals().record['completed_count'],0)
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

    def test_direct_active_entry_requires_ownership(self):
        self.lua.execute("ctx.config.step='enter'; state='go'")
        self.assertEqual(self.run_task()['reason'],'active_task_ownership_missing')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_home_entry_does_not_adopt_an_unrecorded_active_task(self):
        self.lua.execute("ctx.config.step='enter'; state='home'; home_entry_state='go'")
        self.assertEqual(self.run_task()['reason'],'active_task_ownership_missing')
        self.assert_no_accept()


class ScreenCoordinatesTest(unittest.TestCase):
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
