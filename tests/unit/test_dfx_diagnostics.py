"""Exercise production diagnostic defaults without device access."""
from pathlib import Path
import tempfile
import unittest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class DiagnosticDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.globals().folder = self.root.as_posix()
        self.lua.execute('''
            console={}; snapshots=0
            ctx={run_id='fake',config={},sequence=0,screenshot_dir=folder,
                log_path=folder..'/main.log',error_path=folder..'/error.log',profile_path=folder..'/profile.log'}
            nLog=function(line) console[#console+1]=line end
            package.preload['common.screen']=function() return {size=function() return 900,1600 end} end
            snapshot=function(path,x1,y1,x2,y2)
                assert(x1==0 and y1==0 and x2==899 and y2==1599)
                snapshots=snapshots+1
                local f=assert(io.open(path,'wb'));f:write('fake image');f:close()
            end
        ''')

    def test_info_keeps_run_identity_results_and_recovery_without_loop_noise(self):
        self.lua.execute('''
            local l=require('dfx.log')
            for _,event in ipairs({'state','waiting','list_scan','list_drag_unchanged','navigation_state',
                'shimen_delivery','zhuagui_delivery','shimen_find','shimen_puzzle','tap','swipe','new_debug_detail'}) do
                for _=1,10 do l.write(ctx,event,'noise') end
            end
            l.write(ctx,'start','mode=run')
            l.write(ctx,'account','first')
            l.write(ctx,'account_verified','first')
            l.write(ctx,'task_start','shimen')
            l.write(ctx,'find_retry_pending','reason=find_icon_not_found')
            l.write(ctx,'task_result','shimen status=done reason=completion_card_verified')
            l.write(ctx,'summary','daily_done=true')
            l.write(ctx,'finished','script_exited_normally')
        ''')
        text = (self.root / 'main.log').read_text()
        self.assertEqual(len(text.splitlines()), 8)
        self.assertIn('[account] first', text)
        self.assertIn('[task_result] shimen status=done reason=completion_card_verified', text)
        self.assertIn('[finished] script_exited_normally', text)
        self.assertNotIn('noise', text)
        self.assertFalse((self.root / 'error.log').exists())
        self.assertEqual(len(self.lua.globals().console), 8)

    def test_verbose_option_restores_recognition_state_and_input_diagnostics(self):
        self.lua.execute('''
            ctx.config.verbose_logs=true
            local l=require('dfx.log')
            l.write(ctx,'state','battle');l.write(ctx,'find_scan','page=2');l.write(ctx,'tap','target')
        ''')
        text = (self.root / 'main.log').read_text()
        for event in ('state', 'find_scan', 'tap'):
            self.assertIn(f'[{event}]', text)

    def test_normal_process_frames_are_disabled_and_explicit_evidence_is_not_an_error(self):
        self.lua.execute('''
            local s=require('dfx.snapshot')
            for _,label in ipairs({'start','before','after','waiting','completed_card','category_empty'}) do
                assert(s.capture(ctx,label,'debug')==nil)
            end
            s.capture(ctx,'wuji_reward_claim_result','evidence')
        ''')
        self.assertEqual(self.lua.globals().snapshots, 1)
        self.assertEqual(len(list(self.root.glob('*.png'))), 1)
        self.assertIn('[evidence_screenshot]', (self.root / 'main.log').read_text())
        self.assertFalse((self.root / 'error.log').exists())

    def test_failure_and_all_collection_pages_survive_default_switches(self):
        self.lua.execute('''
            local s=require('dfx.snapshot')
            s.capture(ctx,'find_icon_not_found')
            package.preload['tasks.zhuagui.pages']=function() return {
                state=function() return 'find' end,features={find_title={}}} end
            package.preload['common.device']=function() return {swipe=function() return true end} end
            assert(require('tasks.zhuagui.catalog').capture(ctx,'catalog_p').pages==7)
            require('dfx.log').write(ctx,'annotation_required','task=shimen reason=find_icon_not_found')
        ''')
        self.assertEqual(self.lua.globals().snapshots, 8)
        errors = (self.root / 'error.log').read_text()
        self.assertIn('[error_screenshot]', errors)
        self.assertIn('[annotation_required]', errors)
        self.assertNotIn('catalog_p', errors)
        self.assertEqual(len((self.root / 'main.log').read_text().splitlines()), 7)

    def test_process_capture_is_explicitly_enabled_independently_of_verbose_logs(self):
        self.lua.execute("ctx.config.routine_screenshots=true;require('dfx.snapshot').capture(ctx,'before','debug')")
        self.assertEqual(self.lua.globals().snapshots, 1)
        self.assertFalse((self.root / 'error.log').exists())


if __name__ == '__main__':
    unittest.main()
