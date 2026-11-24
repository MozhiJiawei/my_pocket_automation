"""Startup must verify a game page, use Lua once and leave daily tasks untouched."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from lupa import LuaRuntime
from tests.support.touchsprite_adapter import Screen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/device'))


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher=load('application_launcher','scripts/device/start-emulator.py')
runner=load('application_runner','scripts/device/run-daily.py')


class LuaApplicationStartTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            ctx={}; clock=0; launches=0; captures={}; events={}; running=0; ready_at=2; direction=0
            visible='pocket_entry'
            os.time=function() return clock end
            mSleep=function(ms) clock=clock+ms/1000 end
            appIsRunning=function(app) assert(app=='com.netease.mhxyhtb');return running end
            runApp=function(app) assert(app=='com.netease.mhxyhtb');launches=launches+1;running=1 end
            tap=function() error('startup must not tap') end
            package.preload['common.screen']=function() return {
                init=function(value,refresh) assert(refresh);direction=value end} end
            package.preload['common.detector']=function() return {present=function(feature)
                return feature.name==visible and direction==feature.direction and clock>=ready_at
            end} end
            for _,item in ipairs({{'home_dungeon',0},{'saved_account_picker',0},{'pocket_confirm',1},{'pocket_entry',1}}) do
                local name,dir=item[1],item[2]
                package.preload['common.assets.'..name]=function() return {name=name,direction=dir} end
            end
            package.preload['dfx.log']=function() return {write=function(_,event) events[#events+1]=event end} end
            package.preload['dfx.snapshot']=function() return {capture=function(_,label,kind)
                captures[#captures+1]={label=label,kind=kind or 'error'} end} end
        ''')

    def test_cold_game_launches_once_and_requires_visible_entry(self):
        self.lua.execute("result=require('common.application').start(ctx)")
        state=self.lua.globals()
        self.assertEqual(state.result.status,'done')
        self.assertEqual(state.launches,1)
        self.assertEqual(state.clock,2)
        self.assertEqual(len(state.captures),1)
        self.assertEqual(state.captures[1].kind,'evidence')
        self.assertEqual(state.direction,1)

    def test_verified_foreground_entry_is_reused_without_relaunch(self):
        self.lua.execute("running=1;ready_at=0;visible='home_dungeon';result=require('common.application').start(ctx)")
        self.assertEqual(self.lua.globals().result.status,'done')
        self.assertEqual(self.lua.globals().launches,0)
        self.assertEqual(self.lua.globals().direction,0)

    def test_daily_restart_waits_for_exit_before_launching(self):
        self.lua.execute('''
            running=1; visible='pocket_entry'; closes=0
            closeApp=function(app) assert(app=='com.netease.mhxyhtb');closes=closes+1 end
            appIsRunning=function() if launches==0 and clock>=1 then return 0 end;return running end
            local launch=runApp
            runApp=function(app) assert(closes==1 and clock==1);launch(app) end
            result=require('common.application').start(ctx,true)
        ''')
        self.assertEqual(self.lua.globals().result.status,'done')
        self.assertEqual(self.lua.globals().launches,1)

    def test_daily_restart_blocks_when_exit_is_not_verified(self):
        self.lua.execute('''
            running=1; closes=0
            closeApp=function() closes=closes+1 end
            result=require('common.application').start(ctx,true)
        ''')
        state=self.lua.globals()
        self.assertEqual(state.result.reason,'game_close_not_verified')
        self.assertEqual(state.closes,1)
        self.assertEqual(state.launches,0)
        self.assertEqual(state.clock,10)

    def test_background_process_without_game_pixels_is_bounded_and_fails(self):
        self.lua.execute("running=1;visible='unknown';result=require('common.application').start(ctx)")
        state=self.lua.globals()
        self.assertEqual(state.result.status,'blocked')
        self.assertEqual(state.launches,0)
        self.assertEqual(state.clock,120)
        self.assertEqual(len(state.captures),1)
        self.assertEqual(state.captures[1].kind,'error')

    def test_unknown_process_state_blocks_without_launching_or_waiting(self):
        for probe in ('return nil','return -1','return 2','return false',"error('probe_failed')"):
            with self.subTest(probe=probe):
                self.setUp()
                self.lua.execute(f"appIsRunning=function() {probe} end;result=require('common.application').start(ctx)")
                state=self.lua.globals()
                self.assertEqual(state.result.status,'blocked')
                self.assertEqual(state.result.reason,'game_process_state_unknown')
                self.assertEqual(state.launches,0)
                self.assertEqual(state.clock,0)
                self.assertEqual(state.captures[1].label,'game_process_state_unknown')

    def test_lost_process_state_after_launch_does_not_retry_launch(self):
        self.lua.execute('''
            appIsRunning=function() if clock==0 then return 0 end end
            result=require('common.application').start(ctx)
        ''')
        state=self.lua.globals()
        self.assertEqual(state.result.reason,'game_process_state_unknown')
        self.assertEqual(state.launches,1)
        self.assertEqual(state.clock,1)

    def test_running_process_that_stops_during_wait_is_not_relaunched(self):
        self.lua.execute('''
            appIsRunning=function() return clock==0 and 1 or 0 end
            result=require('common.application').start(ctx)
        ''')
        state=self.lua.globals()
        self.assertEqual(state.result.reason,'game_entry_not_verified')
        self.assertEqual(state.launches,0)
        self.assertEqual(state.clock,120)

    def test_failed_diagnostic_does_not_erase_unknown_process_reason(self):
        self.lua.execute('''
            running=nil
            require('dfx.snapshot').capture=function() error('capture_failed') end
            result=require('common.application').start(ctx)
        ''')
        self.assertEqual(self.lua.globals().result.reason,'game_process_state_unknown')
        self.assertEqual(self.lua.globals().launches,0)

    def test_game_pixels_without_running_process_do_not_count(self):
        self.lua.execute("runApp=function() launches=launches+1 end;ready_at=0;result=require('common.application').start(ctx)")
        self.assertEqual(self.lua.globals().result.status,'blocked')
        self.assertEqual(self.lua.globals().launches,1)

    def detect_frame(self,frame):
        screen=Screen(frame)
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        lua.globals().findMultiColorInRegionFuzzy=screen.find
        lua.globals().getScreenSize=lambda: (frame.shape[1],frame.shape[0])
        lua.globals().getColor=screen.color
        lua.globals().keepScreen=lambda held: None
        return lua,lua.eval("require('common.detector')")[0]

    def test_pocket_spinner_matches_failed_cold_entry_and_ignores_ready_pages(self):
        folder=ROOT/'testdata/导航/互通版启动'
        for filename, expected in (('入口加载中.png', True), ('正常入口.png', False),
                                   ('新版入口白天.png', False), ('新版入口夜晚.png', False)):
            with self.subTest(frame=filename):
                lua,detector=self.detect_frame(Screen.read(folder/filename).frame)
                self.assertTrue(detector.present(lua.eval("require('common.assets.pocket_entry')")[0]))
                self.assertEqual(lua.eval("(require('common.pocket_loading'))()"),expected)

    def test_real_entry_and_confirmation_match_but_netease_splash_is_rejected(self):
        folder=ROOT/'testdata/导航/互通版启动'
        cases=json.loads((folder/'预期.json').read_text(encoding='utf-8'))
        for filename,expected in cases.items():
            with self.subTest(frame=filename):
                lua,detector=self.detect_frame(Screen.read(folder/filename).frame)
                for name in ('pocket_entry','pocket_confirm'):
                    feature=lua.eval(f"require('common.assets.{name}')")[0]
                    found=detector.find(feature)
                    self.assertEqual(found is not None,name==expected['page'])
                    if found is not None:
                        offset=found.tap_offset or feature.tap_offset
                        x,y=found.x+offset[1],found.y+offset[2]
                        x1,y1,x2,y2=expected['tap_bounds']
                        self.assertTrue(x1<=x<=x2 and y1<=y<=y2,(filename,name,x,y))

    def test_entry_label_tolerates_small_shifts_and_taps_the_same_button(self):
        folder=ROOT/'testdata/导航/互通版启动'
        cases=json.loads((folder/'预期.json').read_text(encoding='utf-8'))
        for filename,expected in cases.items():
            if expected['page']!='pocket_entry':continue
            frame=Screen.read(folder/filename).frame
            for dx,dy in ((-12,-18),(12,-18),(-12,18),(12,18)):
                with self.subTest(frame=filename,shift=(dx,dy)):
                    shifted=cv2.warpAffine(frame,np.float32([[1,0,dx],[0,1,dy]]),(1600,900))
                    lua,detector=self.detect_frame(shifted)
                    feature=lua.eval("require('common.assets.pocket_entry')")[0]
                    found=detector.find(feature)
                    self.assertIsNotNone(found)
                    offset=found.tap_offset or feature.tap_offset
                    x,y=found.x+offset[1],found.y+offset[2]
                    x1,y1,x2,y2=expected['tap_bounds']
                    self.assertTrue(x1+dx<=x<=x2+dx and y1+dy<=y<=y2+dy,(filename,x,y))

    def test_other_menu_labels_and_entries_outside_the_band_are_rejected(self):
        frame=Screen.read(ROOT/'testdata/导航/互通版启动/新版入口夜晚.png').frame
        # Move the actual recharge/settings/scan labels into the search band;
        # Pocket itself moves below the image. No fabricated label pixels.
        for dx,dy in ((0,112),(0,224),(0,336),(-100,0),(0,-130)):
            with self.subTest(shift=(dx,dy)):
                shifted=cv2.warpAffine(frame,np.float32([[1,0,dx],[0,1,dy]]),(1600,900))
                lua,detector=self.detect_frame(shifted)
                feature=lua.eval("require('common.assets.pocket_entry')")[0]
                self.assertIsNone(detector.find(feature))

    def test_entry_uses_glyph_details_without_the_pet_or_surrounding_scene(self):
        folder=ROOT/'testdata/导航/互通版启动'
        cases=json.loads((folder/'预期.json').read_text(encoding='utf-8'))
        for filename,expected in cases.items():
            if expected['page']!='pocket_entry':continue
            original=Screen.read(folder/filename).frame
            x1,y1,x2,y2=expected['label_bounds']
            with self.subTest(frame=filename):
                frame=np.full_like(original,40)
                frame[y1:y2+1,x1:x2+1]=original[y1:y2+1,x1:x2+1]
                lua,detector=self.detect_frame(frame)
                feature=lua.eval("require('common.assets.pocket_entry')")[0]
                self.assertIsNotNone(detector.find(feature))
                # A bright rectangular patch has no glyph strokes or shadows.
                frame[y1:y2+1,x1:x2+1]=240
                lua,detector=self.detect_frame(frame)
                feature=lua.eval("require('common.assets.pocket_entry')")[0]
                self.assertIsNone(detector.find(feature))


class StartupEvidenceTest(unittest.TestCase):
    valid='[task_result] startup status=done reason=game_entry_verified\n[summary] scope=application_startup daily_done=false\n[finished] script_exited_normally'

    def test_startup_is_never_daily_completion(self):
        result=runner.runtime_result(self.valid,'run','launch-game')
        self.assertTrue(result['expectation_met'])
        self.assertFalse(result['daily_complete'])
        self.assertFalse(result['selected_complete'])

    def test_process_only_other_tasks_and_unfinished_scripts_are_rejected(self):
        for text in (self.valid.replace('game_entry_verified','process_running'),
                     self.valid.replace('startup','dungeon',1),
                     self.valid.replace('daily_done=false','daily_done=true'),
                     self.valid.replace('script_exited_normally','script_failed'),
                     self.valid.replace('scope=application_startup','scope=roles'),
                     '[account] first\n'+self.valid,
                     self.valid+'\n[task_result] shimen status=done reason=done',
                     '[finished] script_exited_normally'):
            with self.subTest(text=text):
                self.assertFalse(runner.runtime_result(text,'run','launch-game')['expectation_met'])

    def test_cli_launch_does_not_read_accounts_or_select_roles(self):
        with patch.object(sys,'argv',['run-daily.py','--vm-index','5','--mode','run','--step','launch-game']), \
                patch.object(runner,'execute') as run, \
                patch.object(runner,'instance_lock',return_value=contextlib.nullcontext()), \
                patch.object(runner,'input_evidence',return_value={}), \
                patch.object(Path,'read_text',side_effect=AssertionError('account read')):
            runner.main()
        self.assertEqual(run.call_args.args[1],[])
        self.assertEqual(run.call_args.args[2],150)

    def test_role_options_and_observe_mode_fail_before_publishing(self):
        for mode,accounts,alias in (('observe',[],None),('run',[{'alias':'first'}],None),('run',[],'first')):
            args=SimpleNamespace(mode=mode,step='launch-game',task='dungeon',account=alias)
            with self.subTest(mode=mode,accounts=accounts,alias=alias), \
                    patch.object(runner,'build') as build:
                with self.assertRaises(ValueError):
                    runner.run_once(args,accounts,150,'fake',Path('unused'))
                build.assert_not_called()


class LuaMainBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            events={};process_calls=0;bootstrap_calls=0;daily_runs=0;task_runs=0;observations=0
            running=1;bootstrap_status='done';bootstrap_reason='game_entry_verified'
            config={mode='run',step='daily',tasks={'shimen'},allow_reward_claim=false,accounts={{alias='first'}}}
            ctx={config=config,run_id='fake'}
            loadfile=function() return function() return config end end
            nLog=function() end
            appIsRunning=function(app)
                assert(app=='com.netease.mhxyhtb');process_calls=process_calls+1
                if probe_error then error('probe_failed') end
                return running
            end
            package.preload['TSLib']=function() return {} end
            package.preload['common.screen']=function() return {init=function() end} end
            package.preload['dfx.run']=function() return {new=function() return ctx end} end
            package.preload['dfx.profile']=function() return {install=function() end,flush=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function(_,label)
                events[#events+1]={'capture',label}
            end} end
            package.preload['dfx.log']=function() return {write=function(_,event,detail)
                events[#events+1]={event,detail}
            end} end
            package.preload['common.application']=function() return {start=function(c,restart)
                bootstrap_calls=bootstrap_calls+1;assert(c==ctx)
                bootstrap_restart=restart
                return {status=bootstrap_status,reason=bootstrap_reason}
            end} end
            package.preload['daily']=function() return {run=function(c)
                assert(c==ctx and c.config==config and c.config.tasks[1]=='shimen')
                daily_runs=daily_runs+1
            end} end
            package.preload['common.navigation']=function() return {prepare_recorded=function()
                error('active task must preserve its page')
            end} end
            package.preload['tasks.shimen.pages']=function() return {state=function() return 'puzzle' end} end
            package.preload['tasks.shimen.task']=function() return {
                run=function() task_runs=task_runs+1;return {status='done',reason='completion_card_verified'} end,
                observe=function() observations=observations+1 end
            } end
        ''')

    def run_main(self):
        self.lua.execute((ROOT/'src/main.lua').read_text(encoding='utf-8'))
        return [(item[1],item[2]) for item in self.lua.globals().events.values()]

    def test_cold_run_bootstraps_once_then_continues_original_daily_scope(self):
        self.lua.execute('running=0')
        events=self.run_main()
        self.assertEqual(self.lua.globals().bootstrap_calls,1)
        self.assertEqual(self.lua.globals().daily_runs,1)
        self.assertFalse(any(event=='task_result' and detail.startswith('startup ') for event,detail in events))

    def test_running_game_restarts_before_daily_tasks_by_default(self):
        self.run_main()
        self.assertEqual(self.lua.globals().bootstrap_calls,1)
        self.assertTrue(self.lua.globals().bootstrap_restart)
        self.assertEqual(self.lua.globals().daily_runs,1)

    def test_active_task_keeps_existing_resume_flow(self):
        self.lua.execute("config.tasks=nil;config.step='complete';config.task='shimen';config.verify_role=true")
        events=self.run_main()
        self.assertEqual(self.lua.globals().bootstrap_calls,0)
        self.assertEqual(self.lua.globals().task_runs,1)
        self.assertTrue(any(event=='screen_resume' for event,_ in events))

    def test_unknown_process_state_blocks_before_startup_or_tasks(self):
        for setup in ('running=nil','running=-1','running=2','running=false','probe_error=true'):
            with self.subTest(setup=setup):
                self.setUp()
                self.lua.execute(setup)
                events=self.run_main()
                self.assertEqual(self.lua.globals().bootstrap_calls,0)
                self.assertEqual(self.lua.globals().daily_runs,0)
                self.assertIn(('task_result','startup status=blocked reason=game_process_state_unknown'),events)
                self.assertIn(('capture','game_process_state_unknown'),events)

    def test_bootstrap_failure_reports_raw_reason_and_stops_original_scope(self):
        self.lua.execute("running=0;bootstrap_status='blocked';bootstrap_reason='game_entry_not_verified'")
        events=self.run_main()
        self.assertEqual(self.lua.globals().bootstrap_calls,1)
        self.assertEqual(self.lua.globals().daily_runs,0)
        self.assertIn(('task_result','startup status=blocked reason=game_entry_not_verified'),events)

    def test_explicit_launch_game_keeps_its_own_startup_acceptance(self):
        self.lua.execute("config.step='launch-game';running=nil")
        events=self.run_main()
        self.assertEqual(self.lua.globals().process_calls,0)
        self.assertEqual(self.lua.globals().bootstrap_calls,1)
        self.assertEqual(self.lua.globals().daily_runs,0)
        self.assertIn(('task_result','startup status=done reason=game_entry_verified'),events)
        self.assertIn(('summary','daily_done=false scope=application_startup'),events)

    def test_observe_does_not_probe_or_start_game(self):
        self.lua.execute("config.mode='observe';config.task='shimen';running=0")
        self.run_main()
        self.assertEqual(self.lua.globals().process_calls,0)
        self.assertEqual(self.lua.globals().bootstrap_calls,0)
        self.assertEqual(self.lua.globals().observations,1)


class ApplicationBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.report = self.folder / 'apps-start.json'
        self.device = Mock()
        self.processes = 'USER PID PPID NAME\nu0_a1 42 1 system_server'
        self.activities = 'ACTIVITY MANAGER ACTIVITIES\nActivityRecord{com.touchsprite.android/.MainActivity}'
        self.services = 'ACTIVITY MANAGER SERVICES\n  (nothing)'
        self.listeners = 'State Recv-Q Send-Q Local_Address:Port Peer_Address:Port\nLISTEN 0 4 *:5555 *:*'
        self.device.adb_call.side_effect = self.adb
        self.device.status.return_value = 'f00'
        self.vm = dict(error_code=0, index='5', is_android_started=True, is_process_started=True, adb_port=16544)
        self.response = Mock()
        self.response.__enter__ = Mock(return_value=self.response)
        self.response.__exit__ = Mock(return_value=False)
        self.response.read.return_value = b'abcdefghijklmnop'
        self.device.http.open.return_value = self.response
        self.clock = 0
        self.calls = []
        self.launch_lost = False

    def adb(self, *args):
        if args[0] == 'forward':
            return '12345'
        if args == ('shell', 'ps', '-A'):
            return self.processes
        if args == ('shell', 'dumpsys', 'activity', 'activities'):
            return self.activities
        if args == ('shell', 'dumpsys', 'activity', 'services', 'com.touchsprite.android'):
            return self.services
        if args == ('shell', 'ss', '-ltn'):
            return self.listeners
        return 'package:/data/app/base.apk'

    def command(self, args, timeout):
        self.calls.append(args)
        if args[1] == 'info':
            return json.dumps(self.vm)
        if self.launch_lost:
            raise TimeoutError('private token must not be persisted')
        return '{"errcode":0}'

    def sleep(self, seconds):
        self.clock += seconds

    def run_apps(self):
        with patch.object(launcher, 'Device', return_value=self.device), \
                patch.object(launcher, 'command', side_effect=self.command), \
                patch.object(launcher.time, 'monotonic', side_effect=lambda: self.clock), \
                patch.object(launcher.time, 'sleep', side_effect=self.sleep), \
                patch.object(launcher, '_load_runner') as runner_loader, \
                contextlib.redirect_stdout(io.StringIO()):
            result = launcher.start_apps(self.folder, 5, '127.0.0.1:16544', self.report)
        runner_loader.assert_not_called()
        return result

    def test_ready_service_is_reused_without_launching_game_or_lua(self):
        result = self.run_apps()
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(result['touchsprite_ready'])
        self.assertNotIn('game_entry_verified', result)
        self.assertEqual(len(self.calls), 1)
        self.device.authorize.assert_called_once_with()
        self.device.status.assert_called_once_with()
        self.device.adb_call.assert_any_call('shell', 'pm', 'path', 'com.touchsprite.android')
        self.assertFalse(any('com.netease.mhxyhtb' in call.args for call in self.device.adb_call.call_args_list))
        self.device.close.assert_called_once_with()

    def test_unavailable_service_launches_only_when_process_is_confirmed_absent(self):
        self.device.http.open.side_effect = [OSError(), OSError(), self.response]
        result = self.run_apps()
        self.assertEqual(result['touchsprite_launch'], 'returned')
        self.assertFalse(result['touchsprite_process_running'])
        self.assertEqual(self.calls[1][1:], ['control', '--vmindex', '5', 'app', 'launch',
                                           '--package', 'com.touchsprite.android'])
        self.assertEqual(len(self.calls), 2)

    def test_live_process_with_unreachable_api_is_waited_without_launch_or_restart(self):
        self.processes += '\nu0_a2 55 1 com.touchsprite.android'
        self.device.http.open.side_effect = OSError('private token must not be persisted')
        with self.assertRaises(TimeoutError):
            self.run_apps()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.clock, 90)
        self.assertNotIn('private token', self.report.read_text())
        self.device.authorize.assert_not_called()
        self.device.close.assert_called_once()

    def test_initialized_auxiliary_process_is_reused(self):
        self.processes += '\nu0_a2 55 1 com.touchsprite.android:service'
        self.device.http.open.side_effect = [OSError(), self.response]
        result = self.run_apps()
        self.assertTrue(result['touchsprite_process_running'])
        self.assertEqual(result['touchsprite_launch'], 'reused')
        self.assertEqual(len(self.calls), 1)

    def test_boot_receiver_process_is_initialized_once_without_stopping_it(self):
        for process in ('com.touchsprite.android', 'com.touchsprite.android:service'):
            with self.subTest(process=process):
                self.setUp()
                self.processes += '\nu0_a2 55 1 ' + process
                self.activities = 'ACTIVITY MANAGER ACTIVITIES\nResumedActivity: app.lawnchair/.Launcher'
                self.device.http.open.side_effect = [OSError(), OSError(), OSError(), self.response]
                result = self.run_apps()
                self.assertTrue(result['touchsprite_process_running'])
                self.assertEqual(result['touchsprite_launch_reason'], 'process_without_activity_service_or_api')
                self.assertEqual(result['touchsprite_launch'], 'returned')
                self.assertEqual(result['touchsprite_api_probe'], 'ready')
                self.assertEqual(result['touchsprite_api_checks'], 4)
                self.assertEqual(result['http_proxy_policy'], 'direct')
                self.assertEqual(len(self.calls), 2)
                self.assertEqual(self.calls[1][4:], ['app', 'launch', '--package', 'com.touchsprite.android'])
                self.device.authorize.assert_called_once_with()
                self.device.status.assert_called_once_with()

    def test_existing_service_or_listener_prevents_initialization_launch(self):
        for protected in ('service', 'listener'):
            with self.subTest(protected=protected):
                self.setUp()
                self.processes += '\nu0_a2 55 1 com.touchsprite.android'
                self.activities = 'ACTIVITY MANAGER ACTIVITIES\nResumedActivity: app.lawnchair/.Launcher'
                if protected == 'service':
                    self.services += '\nServiceRecord{com.touchsprite.android/.service.ServiceMain}'
                else:
                    self.listeners += '\nLISTEN 0 5 0.0.0.0:50005 0.0.0.0:*'
                self.device.http.open.side_effect = OSError('secret')
                with self.assertRaises(TimeoutError):
                    self.run_apps()
                self.assertEqual(len(self.calls), 1)
                self.device.authorize.assert_not_called()
                self.assertNotIn('secret', self.report.read_text())

    def test_boot_initialization_response_loss_never_repeats_launch(self):
        self.processes += '\nu0_a2 55 1 com.touchsprite.android'
        self.activities = 'ACTIVITY MANAGER ACTIVITIES\nResumedActivity: app.lawnchair/.Launcher'
        self.launch_lost = True
        self.device.http.open.side_effect = OSError('private token')
        with self.assertRaises(TimeoutError):
            self.run_apps()
        self.assertEqual(len(self.calls), 2)
        record = json.loads(self.report.read_text())
        self.assertEqual(record['touchsprite_launch'], 'unknown')
        self.assertEqual(record['touchsprite_api_probe'], 'OSError')
        self.assertEqual(record['phase'], 'wait_touchsprite')
        self.assertEqual(self.clock, 90)
        self.assertNotIn('private token', self.report.read_text())
        self.device.authorize.assert_not_called()

    def test_unknown_initialization_evidence_never_launches(self):
        for field in ('activities', 'services', 'listeners'):
            with self.subTest(field=field):
                self.setUp()
                self.processes += '\nu0_a2 55 1 com.touchsprite.android'
                setattr(self, field, 'truncated')
                self.device.http.open.side_effect = OSError()
                with self.assertRaisesRegex(RuntimeError, 'initialization state is unknown'):
                    self.run_apps()
                self.assertEqual(len(self.calls), 1)

    def test_api_becoming_ready_during_inspection_cancels_initialization_launch(self):
        self.processes += '\nu0_a2 55 1 com.touchsprite.android'
        self.activities = 'ACTIVITY MANAGER ACTIVITIES\nResumedActivity: app.lawnchair/.Launcher'
        self.device.http.open.side_effect = [OSError(), self.response, self.response]
        result = self.run_apps()
        self.assertEqual(result['touchsprite_launch'], 'reused')
        self.assertEqual(len(self.calls), 1)

    def test_unknown_process_listing_prevents_launch(self):
        for listing in ('incomplete output', 'USER PID PPID NAME', 'USER PID PPID NAME\nu0_a2 55'):
            with self.subTest(listing=listing):
                self.report.unlink(missing_ok=True)
                self.processes = listing
                self.device.http.open.side_effect = OSError()
                with self.assertRaisesRegex(RuntimeError, 'unknown'):
                    self.run_apps()
        self.assertTrue(all(call[1] == 'info' for call in self.calls))
        self.device.authorize.assert_not_called()

    def test_busy_recording_and_unknown_service_prevent_publication(self):
        for state in ('f01', 'f02', None, 'unknown'):
            with self.subTest(state=state):
                self.report.unlink(missing_ok=True)
                self.device.status.return_value = state
                with self.assertRaisesRegex(RuntimeError, 'busy or unknown'):
                    self.run_apps()
                self.assertEqual(json.loads(self.report.read_text())['status'], 'failed')
        self.assertTrue(all(call[1] == 'info' for call in self.calls))

    def test_wrong_vm_endpoint_prevents_any_app_launch(self):
        self.vm['adb_port'] = 16545
        with self.assertRaises(ValueError):
            self.run_apps()
        self.assertEqual(len(self.calls), 1)
        self.device.adb_call.assert_not_called()

    def test_api_failure_after_single_launch_times_out_without_secrets_or_retries(self):
        self.device.http.open.side_effect = OSError('private token must not be persisted')
        with self.assertRaises(TimeoutError):
            self.run_apps()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.clock, 90)
        self.assertNotIn('private token', self.report.read_text())
        self.device.close.assert_called_once()

    def test_launch_response_loss_is_observed_without_second_request(self):
        self.launch_lost = True
        self.device.http.open.side_effect = [OSError(), OSError(), self.response]
        result = self.run_apps()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['touchsprite_launch'], 'unknown')
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn('private token', self.report.read_text())

    def test_authorization_failure_cannot_report_ready(self):
        self.device.authorize.side_effect = RuntimeError('private token')
        with self.assertRaises(RuntimeError):
            self.run_apps()
        record = json.loads(self.report.read_text())
        self.assertEqual(record['status'], 'failed')
        self.assertFalse(record['touchsprite_ready'])
        self.assertNotIn('private token', self.report.read_text())

if __name__=='__main__':
    unittest.main()
