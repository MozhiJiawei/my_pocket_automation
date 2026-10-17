"""Actual collection, temporary-file lifecycle and same-question guards."""
from pathlib import Path
import tempfile
import unittest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class RecognitionMaterialsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.globals().folder = self.root.as_posix()
        self.lua.execute('''
            position=1400;question=1;state='find';forward=0;backward=0
            ctx={run_id='fake',sequence=0,screenshot_dir=folder,config={},account={alias='first'},
                log_path=folder..'/main.log',error_path=folder..'/error.log'}
            nLog=function() end;keepScreen=function() end
            getColor=function(x,y)
                return y<500 and question*0x121212 or (math.floor(position/400)+1)*0x121212
            end
            package.preload['common.screen']=function() return {size=function() return 900,1600 end} end
            snapshot=function(path,x1,y1,x2,y2)
                assert(x2==899 and y2==1599)
                local f=assert(io.open(path,'wb'));f:write('question='..question..' position='..position);f:close()
            end
            package.preload['tasks.zhuagui.pages']=function() return {
                state=function() return state end,features={find_title='title'}} end
            package.preload['common.device']=function() return {
                swipe=function(c,feature,label,from,to)
                    assert(feature=='title')
                    if label=='catalog_to_top' then
                        backward=backward+1
                        position=math.max(0,position-600)
                    else
                        forward=forward+1;position=math.min(2400,position+400)
                        if expire and forward==2 then state='retry' end
                        if reroll and forward==2 then question=2 end
                    end
                    return true
                end,
                tap=function() error('material collection cannot click candidates or retry') end
            } end
            materials=require('dfx.materials')
        ''')

    def prepare(self, task='shimen', kind='find'):
        return self.lua.execute('return materials.prepare(ctx,...)', task, kind)

    def files(self):
        return sorted(self.root.glob('*.png'))

    def test_full_question_is_collected_before_actions_and_original_first_frame_restored(self):
        self.assertTrue(self.prepare())
        self.assertEqual(self.lua.globals().position, 0)
        self.assertEqual(self.lua.globals().forward, 6)
        self.assertEqual(len(self.files()), 7)
        self.assertTrue(all('_pending_' in path.name for path in self.files()))
        content = [path.read_text() for path in self.files()]
        self.assertEqual(content, [f'question=1 position={p}' for p in range(0,2401,400)])
        self.assertFalse((self.root / 'main.log').exists())
        self.lua.execute('materials.clear(ctx)')
        self.assertEqual(self.files(), [])

    def test_failure_promotes_every_original_once_instead_of_only_the_last_page(self):
        self.prepare('zhuagui')
        self.lua.execute("materials.keep(ctx,'find_icon_not_found');materials.keep(ctx,'outer_failure')")
        self.assertEqual(len(self.files()), 7)
        self.assertFalse(any('_pending_' in path.name for path in self.files()))
        text = (self.root / 'main.log').read_text()
        self.assertEqual(text.count('[recognition_materials]'), 1)
        self.assertIn('pages=7 from_first=true captured=true coverage_verified=false', text)

    def test_timeout_retains_known_pages_but_never_claims_a_complete_collection(self):
        self.lua.execute('expire=true')
        self.assertEqual(self.prepare(), (False,'catalog_page_changed'))
        self.assertEqual(self.lua.globals().forward, 2)
        text = (self.root / 'main.log').read_text()
        self.assertIn('pages=2 from_first=true captured=false', text)
        self.assertFalse(any('_pending_' in path.name for path in self.files()))

    def test_question_change_is_rejected_before_saving_another_questions_candidates(self):
        self.lua.execute('reroll=true')
        self.assertEqual(self.prepare(), (False,'catalog_page_changed'))
        originals = [p for p in self.files() if '_p0' in p.name]
        self.assertEqual(len(originals), 2)
        self.assertTrue(all('question=1' in p.read_text() for p in originals))

    def test_puzzle_original_is_saved_before_mutation_and_kept_until_game_verification(self):
        self.assertTrue(self.prepare(kind='puzzle'))
        original = self.files()[0].read_bytes()
        self.lua.execute("question=2;materials.keep(ctx,'puzzle_game_result_not_verified')")
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.files()[0].read_bytes(), original)

    def test_unverified_round_and_role_are_kept_separately_instead_of_discarded_as_success(self):
        self.prepare(kind='puzzle')
        self.lua.execute("ctx.account={alias='second'};materials.clear(ctx)")
        self.assertEqual(len(self.files()), 1)
        self.prepare('zhuagui', 'puzzle')
        self.lua.execute("materials.keep(ctx,'find_target_unknown')")
        self.assertEqual(len(self.files()), 2)
        text = (self.root / 'main.log').read_text()
        self.assertIn('account=first prefix=shimen_puzzle_r001_', text)
        self.assertIn('account=second prefix=zhuagui_puzzle_r002_', text)


if __name__ == '__main__':
    unittest.main()
