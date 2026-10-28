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
            nLog=function() end;keepScreen=function() end;mSleep=function() end
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
            package.preload['common.detector']=function() return {
                present=function(feature) return feature=='title' and state=='find' end} end
            package.preload['tasks.shimen.assets.questions']=function() return {title='title'} end
            package.preload['tasks.shimen.assets.catalog']=function() return {sample=function() return {} end} end
            package.preload['common.find_items']=function() return {scan=function()
                assert(#ctx.recognition_materials.paths==forward+1,'capture must precede recognition')
                return {}
            end} end
            solver=require('tasks.shimen.find')
            solver.identify=function() return 'sample' end
        ''')

    def prepare(self, task='shimen', kind='find'):
        return self.lua.execute('return materials.prepare(ctx,...)', task, kind)

    def files(self):
        return sorted(self.root.glob('*.png'))

    def enable_profile(self):
        self.lua.execute('''
            now=0;clock_reads=0
            ctx.profile={started=0,clock=function() clock_reads=clock_reads+1;return now end}
            ctx.profile_path=folder..'/profile.log'
            mSleep=function(ms) now=now+ms end
        ''')

    def test_recognition_collects_once_while_scrolling_without_a_return_pass(self):
        self.assertTrue(self.prepare())
        self.assertEqual(self.lua.globals().position, 0)
        self.assertEqual(self.lua.globals().forward, 0)
        backward=self.lua.globals().backward
        self.assertEqual(self.lua.execute('return solver.solve(ctx)'),(False,'find_icon_not_found'))
        self.assertEqual(self.lua.globals().position, 2400)
        self.assertEqual(self.lua.globals().backward, backward)
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
        self.lua.execute('solver.solve(ctx)')
        self.lua.execute("materials.keep(ctx,'find_icon_not_found');materials.keep(ctx,'outer_failure')")
        self.assertEqual(len(self.files()), 7)
        self.assertFalse(any('_pending_' in path.name for path in self.files()))
        text = (self.root / 'main.log').read_text()
        self.assertEqual(text.count('[recognition_materials]'), 1)
        self.assertIn('pages=7 from_first=true captured=true coverage_verified=false', text)

    def test_rotating_item_artwork_does_not_change_the_verified_scroll_position(self):
        self.lua.execute('''
            local color=getColor
            artwork_reads=0
            getColor=function(x,y)
                if y>500 and x>=68 and x<820 then
                    artwork_reads=artwork_reads+1
                    return artwork_reads%2==0 and 0xeeeeee or 0x111111
                end
                return color(x,y)
            end
        ''')
        self.assertTrue(self.prepare())
        self.assertEqual(self.lua.globals().position,0)
        self.assertEqual(self.lua.globals().artwork_reads,0)

    def test_transient_page_read_is_reobserved_without_accepting_another_question(self):
        self.lua.execute('''
            local pages=require('tasks.zhuagui.pages')
            local observed=pages.state
            local swipe=require('common.device').swipe
            require('common.device').swipe=function(...)
                local ok=swipe(...)
                if forward==2 then transient=true end
                return ok
            end
            pages.state=function()
                if transient then transient=false;return 'unknown' end
                return observed()
            end
        ''')
        self.assertTrue(self.prepare())
        self.assertEqual(self.lua.execute('return solver.solve(ctx)'),(False,'find_icon_not_found'))
        self.assertEqual(self.lua.globals().position,2400)

    def test_repeated_row_borders_cannot_match_before_the_stationary_boundary(self):
        self.lua.execute('''
            local color=getColor
            getColor=function(x,y)
                if y>500 then return (math.floor((position%1200)/400)+1)*0x121212 end
                return color(x,y)
            end
        ''')
        self.assertTrue(self.prepare())
        self.assertEqual(self.lua.globals().position,0)
        self.assertGreaterEqual(self.lua.globals().backward,4)

    def test_timeout_retains_known_pages_but_never_claims_a_complete_collection(self):
        self.lua.execute('expire=true')
        self.assertTrue(self.prepare())
        self.assertEqual(self.lua.execute('return solver.solve(ctx)'), (False,'catalog_page_changed'))
        self.assertEqual(self.lua.globals().forward, 2)
        text = (self.root / 'main.log').read_text()
        self.assertIn('pages=2 from_first=true captured=false', text)
        self.assertFalse(any('_pending_' in path.name for path in self.files()))

    def test_partial_failure_emits_one_bounded_trace_linked_to_retained_originals(self):
        self.enable_profile()
        self.lua.execute('expire=true')
        self.assertTrue(self.prepare())
        self.assertFalse((self.root/'profile.log').exists())
        self.assertEqual(self.lua.execute('return solver.solve(ctx)'),(False,'catalog_page_changed'))
        text=(self.root/'profile.log').read_text()
        lines=text.splitlines()
        self.assertLessEqual(len(lines),9)
        self.assertEqual(text.count('scope=find_failure '),1)
        self.assertIn('page=3 phase=stable pages=2 captured=false',text)
        self.assertIn('solver_result=catalog_page_changed',text)
        self.assertIn('state=retry',text)
        self.assertIn('scan=',text)
        self.assertIn('stable=',text)
        self.assertNotIn('_pending_',text)
        for path in self.files():
            self.assertIn('image='+path.name,text)
        self.lua.execute("materials.keep(ctx,'outer_failure')")
        self.assertEqual((self.root/'profile.log').read_text(),text)

    def test_success_and_pending_delivery_are_silent_and_next_role_has_a_fresh_trace(self):
        self.enable_profile()
        self.assertTrue(self.prepare())
        self.lua.execute('''
            require('common.find_items').scan=function()
                return {{x=100,y=700,feature={region={100,700,100,700}}},
                        {x=300,y=700,feature={region={300,700,300,700}}}}
            end
            taps=0
            require('common.device').tap=function()
                taps=taps+1;if taps==2 then state='delivered' end;return true
            end
            require('common.device').wait=function(predicate) return predicate() end
        ''')
        self.assertEqual(self.lua.execute('return solver.solve(ctx)'),(True,'find_completed'))
        self.assertFalse((self.root/'profile.log').exists())
        self.lua.execute("materials.keep(ctx,'delivery_not_verified')")
        self.assertFalse((self.root/'profile.log').exists())
        self.lua.execute("ctx.account={alias='second'};state='find'")
        self.assertTrue(self.prepare())
        self.lua.execute("materials.keep(ctx,'script_failed')")
        text=(self.root/'profile.log').read_text()
        self.assertIn('account=second prefix=shimen_find_r002_',text)
        self.assertNotIn('shimen_find_r001_',text)
        self.assertNotIn('scan=',text)

    def test_verified_delivery_discards_all_trace_data_and_emits_nothing(self):
        self.enable_profile()
        self.assertTrue(self.prepare())
        self.lua.execute("require('dfx.find_profile').result(ctx,true,'find_completed');materials.clear(ctx)")
        self.assertIsNone(self.lua.globals().ctx.recognition_materials)
        self.assertFalse((self.root/'profile.log').exists())

    def test_question_change_is_rejected_before_saving_another_questions_candidates(self):
        self.lua.execute('reroll=true')
        self.assertTrue(self.prepare())
        self.assertEqual(self.lua.execute('return solver.solve(ctx)'), (False,'catalog_page_changed'))
        originals = [p for p in self.files() if '_p0' in p.name]
        self.assertEqual(len(originals), 2)
        self.assertTrue(all('question=1' in p.read_text() for p in originals))

    def test_success_on_second_page_stops_collection_and_keeps_partial_material_pending_delivery(self):
        self.assertTrue(self.prepare())
        backward=self.lua.globals().backward
        self.lua.execute('''
            taps=0
            require('common.find_items').scan=function()
                assert(#ctx.recognition_materials.paths==forward+1)
                if forward==0 then return {} end
                return {{x=100,y=700,feature={region={100,700,100,700}}},
                        {x=300,y=700,feature={region={300,700,300,700}}}}
            end
            require('common.device').tap=function()
                taps=taps+1
                if taps==2 then state='delivered' end
                return true
            end
            require('common.device').wait=function(predicate) return predicate() end
        ''')
        self.assertEqual(self.lua.execute('return solver.solve(ctx)'),(True,'find_completed'))
        self.assertEqual(self.lua.globals().forward,1)
        self.assertEqual(self.lua.globals().backward,backward)
        self.assertEqual(len(self.files()),2)
        self.assertFalse(self.lua.globals().ctx.recognition_materials.captured)
        self.lua.execute("materials.keep(ctx,'delivery_not_verified')")
        self.assertIn('pages=2 from_first=true captured=false', (self.root/'main.log').read_text())

    def test_unknown_topic_collects_one_full_read_only_traversal(self):
        self.assertTrue(self.prepare())
        backward=self.lua.globals().backward
        self.lua.execute("solver.identify=function() return nil,'find_target_unknown' end")
        self.assertEqual(self.lua.execute('return solver.solve(ctx)'),(False,'find_target_unknown'))
        self.assertEqual(self.lua.globals().forward,6)
        self.assertEqual(self.lua.globals().backward,backward)
        self.assertEqual(len(self.files()),7)
        self.assertTrue(self.lua.globals().ctx.recognition_materials.captured)

    def test_current_page_is_not_captured_until_scroll_inertia_stops(self):
        self.assertTrue(self.prepare())
        self.lua.execute('''
            position=900;settling=3
            mSleep=function()
                if settling>0 then position=position-100;settling=settling-1 end
            end
        ''')
        self.assertTrue(self.lua.execute('return materials.capture_find(ctx,1)'))
        self.assertEqual(self.lua.globals().settling,0)
        self.assertEqual(self.files()[0].read_text(),'question=1 position=600')

    def test_question_fade_in_settles_before_its_identity_is_fixed(self):
        self.lua.execute('''
            sleeps=0
            mSleep=function()
                sleeps=sleeps+1
                if sleeps==1 then question=2 end
            end
        ''')
        self.assertTrue(self.prepare())
        self.assertEqual(self.lua.globals().question,2)
        self.assertTrue(self.lua.execute('return materials.capture_find(ctx,1)'))
        self.assertEqual(self.files()[0].read_text(),'question=2 position=0')

    def test_continuously_moving_page_stops_without_capturing_or_answering(self):
        self.assertTrue(self.prepare())
        self.lua.execute('mSleep=function() position=position+400 end')
        self.assertEqual(self.lua.execute('return materials.capture_find(ctx,1)'),
                         (False,'catalog_scroll_not_stable'))
        self.assertEqual(self.files(),[])

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
