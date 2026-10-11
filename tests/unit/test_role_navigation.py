"""Exercise production roster verification without reading real role profiles."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class RoleNavigationTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            scene='picker'; selected='first'; swipes=0; taps={}; logs={}
            ctx={config={accounts={{alias='first'},{alias='second'}}},account={alias='second'}}
            getScreenSize=function() return 900,1600 end; init=function() end
            loadfile=function(path)
                local alias=path:match('daily_selector_(%w+)')
                if alias then return function() return {kind='selector',alias=alias} end end
                alias=path:match('daily_identity_(%w+)')
                if alias then return function() return {kind='identity',alias=alias} end end
            end
            for module,kind in pairs({home_dungeon='home',pocket_entry='entry',pocket_confirm='confirm',saved_account_picker='picker',saved_account_switch='switch',current_role_marker='marker',saved_role_tile='tile'}) do
                local k=kind
                package.preload['common.assets.'..module]=function() return {kind=k} end
            end
            package.preload['tasks.dungeon.assets.overview_back']=function() return {kind='back'} end
            package.preload['dfx.log']=function() return {write=function(c,e,d) logs[#logs+1]={e,d} end} end
            package.preload['common.detector']=function() return {
                present=function(f)
                    if f.kind=='home' then return scene=='home' end
                    if f.kind=='picker' then return scene=='picker' end
                    if f.kind=='identity' then return scene=='home' and f.alias==selected and not identity_mismatch end
                    if f.kind=='selector' then return scene=='picker' and f.alias~=missing_selector end
                    return false
                end,
                find=function(f)
                    local dy=moving_roster and swipes*3 or 0
                    if scene~='picker' then return nil end
                    if f.kind=='selector' then
                        if hidden_names then return nil end
                        if f.alias==missing_selector then return nil end
                        return {x=f.alias=='first' and 199 or duplicate_owner and 199 or 661,y=584+dy}
                    end
                    if f.kind=='tile' then
                        if hidden_tiles then return nil end
                        if f.region[2]<=426+dy then return {x=f.region[1]<500 and 194 or 589,y=426+dy} end
                        if unknown_role and f.region[1]<500 and f.region[2]<=800 then return {x=194,y=800} end
                    end
                end
            } end
            package.preload['common.device']=function() return {
                wait=function(p,attempts)
                    for index=1,attempts or 1 do
                        if p() then return true end
                        if names_clear_after and index>=names_clear_after then hidden_names=false end
                        if tiles_clear_after and index>=tiles_clear_after then hidden_tiles=false end
                    end
                    return false
                end,
                tap=function(c,f,label)
                    taps[#taps+1]=label
                    if f.kind=='switch' then scene='picker'
                    elseif f.kind=='back' then scene='home'
                    elseif f.kind=='selector' then selected=f.alias;scene='home' end
                    return true
                end,
                swipe=function() swipes=swipes+1;return true end
            } end
        ''')
        self.module=self.lua.eval("require('common.navigation')")[0]

    def test_verified_roster_returns_home_and_restores_list(self):
        self.assertTrue(self.module.verify_roster(self.lua.globals().ctx))
        self.assertEqual(self.lua.globals().scene,'home')
        self.assertEqual(self.lua.globals().swipes,2)

    def test_unknown_tile_cannot_be_silently_omitted(self):
        self.lua.execute('unknown_role=true')
        self.assertFalse(self.module.verify_roster(self.lua.globals().ctx))

    def test_configured_but_missing_role_blocks_completion(self):
        self.lua.execute("missing_selector='second'")
        self.assertFalse(self.module.verify_roster(self.lua.globals().ctx))

    def test_two_names_cannot_claim_the_same_tile(self):
        self.lua.execute('duplicate_owner=true')
        self.assertFalse(self.module.verify_roster(self.lua.globals().ctx))

    def test_roster_scan_has_a_limit(self):
        self.lua.execute('moving_roster=true')
        self.assertFalse(self.module.verify_roster(self.lua.globals().ctx))
        self.assertEqual(self.lua.globals().swipes,7)

    def test_switch_requires_matching_identity_after_selection(self):
        self.lua.execute("scene='home'")
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertEqual(self.lua.globals().selected,'second')
        self.assertTrue(self.lua.globals().ctx.identity_verified)

    def test_wrong_identity_after_switch_is_rejected(self):
        self.lua.execute("scene='home'; identity_mismatch=true")
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(bool(self.lua.globals().ctx.identity_verified))

    def test_transient_overlay_waits_for_all_visible_names_without_extra_clicks(self):
        self.lua.execute('hidden_names=true;names_clear_after=2')
        self.assertTrue(self.module.verify_roster(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['close_verified_roster'])

    def test_permanently_unreadable_names_do_not_relax_roster_validation(self):
        self.lua.execute('hidden_names=true')
        self.assertFalse(self.module.verify_roster(self.lua.globals().ctx))
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_role_tiles_are_recounted_after_picker_loads(self):
        self.lua.execute('hidden_tiles=true;tiles_clear_after=2')
        self.assertTrue(self.module.verify_roster(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['close_verified_roster'])

    def test_quota_dialogue_closes_before_returning_home(self):
        self.lua.execute('''
            scene='quota_dialogue'
            package.preload['tasks.dungeon.pages']=function() return {state=function() return 'unknown' end} end
            package.preload['tasks.zhuagui.pages']=function() return {
                state=function() return scene end,features={quota_dialogue={kind='quota_dialogue'}}
            } end
            package.preload['common.assets.home_tab']=function() return {kind='home_tab'} end
            local device=require('common.device')
            device.tap=function(c,f,label)
                taps[#taps+1]=label
                if f.kind=='quota_dialogue' then scene='task_list'
                elseif f.kind=='home_tab' then scene='home' end
                return true
            end
        ''')
        self.assertTrue(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['close_completed_ghost_dialogue','return_home_from_tasks'])

    def test_quota_dialogue_with_unverified_close_cannot_reach_home(self):
        self.lua.execute('''
            scene='quota_dialogue'
            package.preload['tasks.dungeon.pages']=function() return {state=function() return 'unknown' end} end
            package.preload['tasks.zhuagui.pages']=function() return {
                state=function() return scene end,features={quota_dialogue={kind='quota_dialogue'}}
            } end
        ''')
        self.assertFalse(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['close_completed_ghost_dialogue'])

    def configure_switch_recovery(self, verified):
        self.lua.execute('''
            scene='switch_chechi_wuji'
            package.preload['tasks.dungeon.pages']=function() return {
                state=function() return scene end,
                features={switch_chechi_wuji={kind='switch',tap_offset={100,200}},list_back={kind='list_back'}}
            } end
            require('common.device').tap=function(c,f,label)
                taps[#taps+1]=label
                if f.kind=='switch' then
                    assert(f.tap_offset[1]==-290 and f.tap_offset[2]==200)
                    scene=close_verified and 'list_wuji' or 'unknown'
                elseif f.kind=='list_back' then scene='home' end
                return true
            end
        ''')
        self.lua.globals().close_verified=verified

    def test_restore_switch_only_cancels_then_verifies_list(self):
        self.configure_switch_recovery(True)
        self.assertTrue(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['cancel_dungeon_switch','return_home'])

    def test_restore_switch_stops_if_cancel_does_not_reach_list(self):
        self.configure_switch_recovery(False)
        self.assertFalse(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['cancel_dungeon_switch'])


if __name__=='__main__': unittest.main()
