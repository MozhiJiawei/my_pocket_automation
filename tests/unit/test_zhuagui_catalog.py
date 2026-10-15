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
                state=function() return state end,features={retry='retry',find_title='find_title',dialogue_next='dialogue',depart='depart'}
            } end
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                table.insert(shots,label)
            end} end
            package.preload['dfx.log']=function() return {write=function() end} end
            topic_reads=0
            package.preload['tasks.zhuagui.find']=function() return {identify=function()
                topic_reads=topic_reads+1
                if unknown_topic then return nil,nil,'find_target_unknown' end
                if outside_wine then return 'gold','黄金' end
                if late_topic and topic_reads==11 then return 'plum_wine','酒' end
                return topic_reads%2==0 and 'tiger_wine' or 'dew_wine','酒'
            end} end
            package.preload['common.device']=function() return {
                tap=function(c,feature)
                    assert(feature=='retry' or feature=='dialogue' or feature=='depart','candidate/accept clicks forbidden')
                    table.insert(taps,feature); state=delayed_open and 'unknown' or feature=='dialogue' and 'depart' or 'find'; return true
                end,
                swipe=function(c,feature)
                    assert(feature=='find_title'); swipes=swipes+1
                    if expire_page then state='retry'; return false end
                    if expire_after_swipe then state='retry'; return true end
                    return not break_page
                end,
                wait=function(predicate)
                    if predicate() then return true end
                    state=delayed_open and state=='unknown' and 'find' or 'retry'; return predicate()
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

    def test_existing_npc_dialogue_is_free_preparation_only(self):
        self.lua.execute("state='dialogue';ctx.config.browse_rounds=1")
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'find_catalog_observation_only')
        self.assertEqual(list(self.lua.globals().taps.values()),['dialogue','depart'])

    def test_retry_waits_for_known_page_after_transient_overlay(self):
        self.lua.execute("delayed_open=true;ctx.config.browse_rounds=1")
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'find_catalog_observation_only')
        self.assertEqual(len(self.lua.globals().shots),7)

    def test_paid_accept_page_is_never_used_for_sampling(self):
        self.lua.execute("state='ready_cost_three'")
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'catalog_prepare_not_verified')
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_capture_current_page_never_prepares_or_retries(self):
        self.lua.execute("state='retry'")
        self.assertEqual(self.collector.capture(self.lua.globals().ctx,'failure_')['reason'],'catalog_find_not_open')
        self.assertEqual(len(self.lua.globals().taps),0)
        self.assertEqual(self.lua.globals().swipes,0)
        self.lua.execute("state='find'")
        self.assertEqual(self.collector.capture(self.lua.globals().ctx,'failure_')['pages'],7)
        self.assertEqual(len(self.lua.globals().taps),0)
        self.assertEqual(self.lua.globals().swipes,6)

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

    def test_cycles_stop_only_after_a_full_ten_round_cycle_without_new_topics(self):
        self.lua.execute('ctx.config.browse_rounds=10;ctx.config.browse_until_no_new_topics=true')
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'find_catalog_no_new_topics')
        self.assertEqual(self.lua.globals().topic_reads,20)
        self.assertEqual(len(self.lua.globals().taps),20)
        self.assertEqual(self.lua.globals().swipes,120)

    def test_new_topic_in_second_cycle_requires_a_third_cycle(self):
        self.lua.execute('ctx.config.browse_rounds=10;ctx.config.browse_until_no_new_topics=true;late_topic=true')
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'find_catalog_no_new_topics')
        self.assertEqual(self.lua.globals().topic_reads,30)

    def test_unknown_or_non_wine_topic_cannot_count_as_no_new_topics(self):
        self.lua.execute('ctx.config.browse_rounds=10;ctx.config.browse_until_no_new_topics=true;unknown_topic=true')
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'catalog_wine_topic_not_verified')
        self.assertEqual(self.lua.globals().swipes,0)
        self.lua.execute('unknown_topic=false;outside_wine=true')
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'catalog_wine_topic_not_verified')
        self.assertEqual(self.lua.globals().swipes,0)

    def test_invalid_cycle_size_does_not_retry(self):
        self.lua.execute('ctx.config.browse_until_no_new_topics=true')
        self.assertEqual(self.collector.collect(self.lua.globals().ctx)['reason'],'catalog_cycle_requires_ten_rounds')
        self.assertEqual(len(self.lua.globals().taps),0)

if __name__=='__main__': unittest.main()
