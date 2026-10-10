"""Sampling may only retry and scroll; it cannot solve or accept a paid task."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            state='retry'; taps={}; swipes=0; shots={}
            ctx={config={browse_rounds=2}}
            package.preload['tasks.zhuagui.pages']=function() return {
                state=function() return state end,features={retry='retry',find_title='find_title'}
            } end
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                table.insert(shots,label)
            end} end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['common.device']=function() return {
                tap=function(c,feature)
                    assert(feature=='retry','candidate/accept clicks forbidden')
                    table.insert(taps,feature); state='find'; return true
                end,
                swipe=function(c,feature)
                    assert(feature=='find_title'); swipes=swipes+1
                    if expire_page then state='retry'; return false end
                    if expire_after_swipe then state='retry'; return true end
                    return not break_page
                end,
                wait=function(predicate)
                    if predicate() then return true end
                    state='retry'; return predicate()
                end
            } end
        ''')
        self.collector=self.lua.eval("require('tasks.zhuagui.catalog')")[0]

    def test_multiple_rounds_only_retry_and_scroll(self):
        result=self.collector.collect(self.lua.globals().ctx)
        self.assertEqual(result['reason'],'find_catalog_observation_only')
        self.assertEqual(list(self.lua.globals().taps.values()),['retry','retry'])
        self.assertEqual(self.lua.globals().swipes,12)
        self.assertEqual(len(self.lua.globals().shots),14)
        self.assertEqual(self.lua.globals().shots[8],'catalog_r002_p01')

    def test_changed_page_is_incomplete(self):
        self.lua.execute('break_page=true')
        result=self.collector.collect(self.lua.globals().ctx)
        self.assertEqual(result['reason'],'catalog_page_changed')
        self.assertEqual(list(self.lua.globals().shots.values()),['catalog_r001_p01','catalog_r001_incomplete'])

    def test_invalid_rounds_do_nothing(self):
        self.lua.execute('ctx.config.browse_rounds=61')
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'invalid_catalog_rounds')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_countdown_expiry_retries_without_selecting_candidates(self):
        self.lua.execute('expire_page=true')
        result=self.collector.collect(self.lua.globals().ctx)
        self.assertEqual(result['reason'],'find_catalog_observation_only')
        self.assertEqual(list(self.lua.globals().taps.values()),['retry','retry'])
        self.assertEqual(list(self.lua.globals().shots.values()),[
            'catalog_r001_p01','catalog_r001_incomplete',
            'catalog_r002_p01','catalog_r002_incomplete'])

    def test_expiry_after_swipe_does_not_save_a_candidate_page(self):
        self.lua.execute('expire_after_swipe=true')
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'find_catalog_observation_only')
        self.assertNotIn('catalog_r001_p02',list(self.lua.globals().shots.values()))

if __name__=='__main__': unittest.main()
