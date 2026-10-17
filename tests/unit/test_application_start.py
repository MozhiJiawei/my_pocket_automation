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

    def test_background_process_without_game_pixels_is_bounded_and_fails(self):
        self.lua.execute("running=1;visible='unknown';result=require('common.application').start(ctx)")
        state=self.lua.globals()
        self.assertEqual(state.result.status,'blocked')
        self.assertEqual(state.launches,1)
        self.assertEqual(state.clock,120)
        self.assertEqual(len(state.captures),1)
        self.assertEqual(state.captures[1].kind,'error')

    def test_game_pixels_without_running_process_do_not_count(self):
        self.lua.execute("runApp=function() launches=launches+1 end;ready_at=0;result=require('common.application').start(ctx)")
        self.assertEqual(self.lua.globals().result.status,'blocked')
        self.assertEqual(self.lua.globals().launches,1)

    def test_real_entry_and_confirmation_match_but_netease_splash_is_rejected(self):
        folder=ROOT/'testdata/导航/互通版启动'
        for filename,expected in (('正常入口.png','pocket_entry'),('口袋确认.png','pocket_confirm'),('网易启动画面.png',None)):
            with self.subTest(frame=filename):
                screen=Screen.read(folder/filename)
                lua=LuaRuntime(unpack_returned_tuples=True)
                lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
                lua.globals().findMultiColorInRegionFuzzy=screen.find
                lua.execute("package.preload['common.screen']=function() return {size=function() return 1600,900 end} end")
                for name in ('pocket_entry','pocket_confirm'):
                    matched=lua.eval("function(name) return require('common.detector').present(require('common.assets.'..name)) end")(name)
                    self.assertEqual(matched,name==expected)


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
        with patch.object(sys,'argv',['run-daily.py','--device','fake','--mode','run','--step','launch-game']), \
                patch.object(runner,'run_once') as run,patch.object(Path,'read_text',side_effect=AssertionError('account read')):
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


class ApplicationBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.report=self.folder/'apps-start.json'
        self.device=Mock()
        self.device.adb_call.side_effect=lambda *args: '12345' if args[0]=='forward' else 'package:/data/app/base.apk'
        self.device.status.return_value='f00'
        self.vm=dict(error_code=0,index='5',is_android_started=True,is_process_started=True,adb_port=16544)
        self.response=Mock()
        self.response.__enter__=Mock(return_value=self.response)
        self.response.__exit__=Mock(return_value=False)
        self.response.read.return_value=b'abcdefghijklmnop'
        self.device.http.open.return_value=self.response
        self.lua=Mock()
        self.clock=0
        self.probes=[]
        self.calls=[]

    def command(self,args,timeout):
        self.calls.append(args)
        return json.dumps(self.vm if args[1]=='info' else {'errcode':0})

    def sleep(self,seconds):
        self.clock+=seconds

    def run_apps(self):
        with patch.object(launcher,'Device',return_value=self.device), \
                patch.object(launcher,'command',side_effect=self.command), \
                patch.object(launcher.time,'monotonic',side_effect=lambda:self.clock), \
                patch.object(launcher.time,'sleep',side_effect=self.sleep), \
                patch.object(launcher.importlib.util,'module_from_spec',return_value=self.lua), \
                patch.object(launcher.importlib.util,'spec_from_file_location') as spec, \
                contextlib.redirect_stdout(io.StringIO()):
            spec.return_value.loader.exec_module.return_value=None
            return launcher.start_apps(self.folder,5,'127.0.0.1:16544',self.report)

    def test_ready_service_is_reused_and_game_only_runs_via_lua(self):
        result=self.run_apps()
        self.assertEqual(result['status'],'ready')
        self.assertTrue(result['game_entry_verified'])
        self.assertEqual(len(self.calls),1)
        args,accounts,seconds,*_=self.lua.run_once.call_args.args
        self.assertEqual(args.step,'launch-game')
        self.assertEqual(args.device,'127.0.0.1:16544')
        self.assertEqual(accounts,[])
        self.assertEqual(seconds,150)
        self.device.close.assert_called_once()

    def test_unavailable_service_launches_only_touchsprite_on_exact_vm(self):
        self.device.http.open.side_effect=[OSError(),self.response]
        result=self.run_apps()
        self.assertEqual(result['touchsprite_launch'],'returned')
        self.assertEqual(self.calls[1][1:],['control','--vmindex','5','app','launch','--package','com.touchsprite.android'])
        self.assertEqual(len(self.calls),2)

    def test_busy_service_prevents_publication(self):
        self.device.status.return_value='f01'
        with self.assertRaisesRegex(RuntimeError,'busy'):
            self.run_apps()
        self.lua.run_once.assert_not_called()
        self.device.close.assert_called_once()
        self.assertEqual(json.loads(self.report.read_text())['status'],'failed')

    def test_wrong_vm_endpoint_prevents_any_app_launch(self):
        self.vm['adb_port']=16545
        with self.assertRaises(ValueError):
            self.run_apps()
        self.assertEqual(len(self.calls),1)
        self.device.adb_call.assert_not_called()
        self.lua.run_once.assert_not_called()

    def test_api_failure_times_out_without_repeated_launch_or_secret_in_report(self):
        self.device.http.open.side_effect=OSError('private token must not be persisted')
        with self.assertRaises(TimeoutError):
            self.run_apps()
        self.assertEqual(len(self.calls),2)
        self.assertNotIn('private token',self.report.read_text())
        self.lua.run_once.assert_not_called()
        self.device.close.assert_called_once()

    def test_lua_failure_cannot_report_ready_or_daily_completion(self):
        self.lua.run_once.side_effect=RuntimeError('unverified')
        with self.assertRaises(RuntimeError):
            self.run_apps()
        result=json.loads(self.report.read_text())
        self.assertEqual(result['status'],'failed')
        self.assertNotIn('game_entry_verified',result)


if __name__=='__main__':
    unittest.main()
