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
            getScreenSize=function() return 900,1600 end; init=function() end; mSleep=function() end
            closeApp=function() end;runApp=function() scene='entry' end
            package.preload['common.pocket_loading']=function()
                return function() return entry_loading==true end
            end
            loadfile=function(path)
                local alias=path:match('daily_selector_(%w+)')
                if alias then return function() return {kind='selector',alias=alias} end end
                alias=path:match('daily_identity_(%w+)')
                if alias then return function() return {kind='identity',alias=alias} end end
            end
            for module,kind in pairs({home_dungeon='home',pocket_entry='entry',pocket_confirm='confirm',saved_account_picker='picker',saved_account_switch='switch',current_role_marker='marker',saved_role_tile='tile',saved_role_current_tile='selected_tile',incident_notice='incident',settings_page='settings_page',settings_back='settings_back',settings='settings'}) do
                local k=kind
                package.preload['common.assets.'..module]=function() return {kind=k} end
            end
            package.preload['tasks.dungeon.assets.overview_back']=function() return {kind='back'} end
            package.preload['dfx.log']=function() return {write=function(c,e,d) logs[#logs+1]={e,d} end} end
            package.preload['common.detector']=function() return {
                present=function(f)
                    if f.kind=='incident' then return incident_visible==true end
                    if f.kind=='settings_page' then return scene=='settings' end
                    if f.kind=='entry' then return scene=='entry' end
                    if f.kind=='confirm' then return scene=='confirm' end
                    if f.kind=='home' then return scene=='home' end
                    if f.kind=='switch' then return scene=='home' end
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
                        if selected_badge and f.region[1]<500 then
                            if f.region[2]<=800 then return {x=194,y=800} end
                            return nil
                        end
                        if f.region[2]<=426+dy then return {x=f.region[1]<500 and 194 or 589,y=426+dy} end
                        if unknown_role and f.region[1]<500 and f.region[2]<=800 then return {x=194,y=800} end
                    end
                    if f.kind=='selected_tile' and selected_badge and f.region[1]<500 and f.region[2]<=426 then
                        return {x=194,y=426}
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
                    if f.kind=='incident' then incident_visible=false
                    elseif f.kind=='settings_back' then if not blocked_settings then scene='home' end
                    elseif f.kind=='settings' then scene='settings'
                    elseif f.kind=='entry' then scene='confirm'
                    elseif f.kind=='confirm' then scene='home'
                    elseif f.kind=='switch' then scene='picker'
                    elseif f.kind=='back' then scene='home'
                    elseif f.kind=='selector' then selected=f.alias;scene='home' end
                    return true
                end,
                swipe=function() swipes=swipes+1;return true end
            } end
        ''')
        self.module=self.lua.eval("require('common.navigation')")[0]

    def test_home_identity_matches_configured_role_without_mutation(self):
        self.lua.execute("scene='home';selected='second';ctx.identity_verified=false")
        state=self.lua.globals()
        self.assertTrue(self.module.home_identity_matches(state.ctx))
        self.assertFalse(state.ctx.identity_verified)
        self.assertEqual(len(state.taps),0)
        self.assertEqual(len(state.logs),0)

    def test_home_identity_rejects_wrong_role_even_after_prior_verification(self):
        self.lua.execute("scene='home';ctx.identity_verified=true")
        state=self.lua.globals()
        self.assertFalse(self.module.home_identity_matches(state.ctx))
        self.assertTrue(state.ctx.identity_verified)
        self.assertEqual(state.selected,'first')
        self.assertEqual(len(state.taps),0)
        self.assertEqual(len(state.logs),0)

    def test_home_identity_requires_visible_home_landmark(self):
        self.lua.execute('''
            scene='task_list';selected='second'
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                return f.kind=='identity' or present(f)
            end
        ''')
        self.assertFalse(self.module.home_identity_matches(self.lua.globals().ctx))

    def test_home_identity_rejects_unavailable_or_malformed_resource(self):
        self.lua.execute("scene='home';selected='second'")
        for response in (
            "return nil, 'missing'",
            "return function() error('invalid identity resource') end",
            "return function() return 'invalid identity feature' end",
            "return function() return setmetatable({}, {__index=function() error('invalid identity feature') end}) end",
        ):
            with self.subTest(response=response):
                self.lua.execute(f"loadfile=function(path) {response} end")
                self.assertFalse(self.module.home_identity_matches(self.lua.globals().ctx))

    def test_verified_roster_returns_home_and_restores_list(self):
        self.assertTrue(self.module.verify_roster(self.lua.globals().ctx))
        self.assertEqual(self.lua.globals().scene,'home')
        self.assertEqual(self.lua.globals().swipes,2)

    def test_unresponsive_game_restarts_and_rechecks_identity(self):
        self.lua.execute('''
            scene='anr';ctx.identity_verified=true;restarts=0
            package.preload['common.assets.game_not_responding']=function() return {kind='anr'} end
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                if f.kind=='anr' then return scene=='anr' end
                return present(f)
            end
            runApp=function() restarts=restarts+1;scene='entry' end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)
        self.lua.execute("scene='anr'")
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)

    def test_network_disconnect_restarts_once_and_rechecks_identity(self):
        self.lua.execute('''
            scene='disconnected';ctx.identity_verified=true;restarts=0
            package.preload['common.assets.network_disconnected']=function() return {kind='disconnected'} end
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                if f.kind=='disconnected' then return scene=='disconnected' end
                return present(f)
            end
            runApp=function() restarts=restarts+1;scene='entry' end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)
        self.lua.execute("scene='disconnected'")
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)

    def test_server_list_error_restarts_once_and_rechecks_identity(self):
        self.lua.execute('''
            scene='server_error';ctx.identity_verified=true;restarts=0
            package.preload['common.assets.server_list_network_error']=function() return {kind='server_error'} end
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                if f.kind=='server_error' then return scene=='server_error' end
                return present(f)
            end
            runApp=function() restarts=restarts+1;scene='entry' end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)
        self.lua.execute("scene='server_error'")
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)

    def test_persistent_server_list_error_stops_after_one_restart(self):
        self.lua.execute('''
            scene='server_error';ctx.identity_verified=true;restarts=0
            package.preload['common.assets.server_list_network_error']=function() return {kind='server_error'} end
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                if f.kind=='server_error' then return scene=='server_error' end
                return present(f)
            end
            runApp=function() restarts=restarts+1 end
        ''')
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)
        self.assertEqual(self.lua.globals().logs[len(self.lua.globals().logs)][2],
                         'server_list_network_error')

    def test_selected_badge_precedes_a_lower_generic_tile(self):
        self.lua.execute("selected_badge=true;ctx.config.accounts[3]={alias='third'};local old=require('common.detector').find;require('common.detector').find=function(f) if f.kind=='selector' and f.alias=='third' then return {x=199,y=958} end;return old(f) end")
        self.assertTrue(self.module.verify_roster(self.lua.globals().ctx))

    def test_incident_overlay_is_closed_before_home_is_accepted(self):
        self.lua.execute("scene='home';incident_visible=true")
        self.assertTrue(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['close_incident_notice'])
        self.assertFalse(self.lua.globals().incident_visible)

    def test_bonus_receipt_is_closed_before_underlying_home_is_accepted(self):
        self.lua.execute('''
            scene='home';receipt_visible=true
            local rewards=require('tasks.rewards.pages')
            rewards.features.bonus_receipt={kind='bonus_receipt'}
            rewards.close_receipt=function()
                taps[#taps+1]='close_bonus_receipt';receipt_visible=false;return true
            end
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                if f.kind=='bonus_receipt' then return receipt_visible end
                return present(f)
            end
        ''')
        self.assertTrue(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()), ['close_bonus_receipt'])

    def test_stuck_bonus_receipt_cannot_accept_underlying_home(self):
        self.lua.execute('''
            scene='home'
            local rewards=require('tasks.rewards.pages')
            rewards.features.bonus_receipt={kind='bonus_receipt'}
            rewards.close_receipt=function() return false end
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                return f.kind=='bonus_receipt' or present(f)
            end
        ''')
        self.assertFalse(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(len(self.lua.globals().taps), 0)

    def test_stuck_settings_restarts_only_game_then_checks_identity(self):
        self.lua.execute('''
            scene='settings';blocked_settings=true;restarts={}
            closeApp=function(id) restarts[#restarts+1]={'close',id} end
            runApp=function(id) restarts[#restarts+1]={'run',id};scene='entry';selected='second' end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual([(x[1],x[2]) for x in self.lua.globals().restarts.values()],
                         [('close','com.netease.mhxyhtb'),('run','com.netease.mhxyhtb')])

    def test_selected_role_with_stale_home_reenters_before_identity_is_verified(self):
        self.lua.execute('''
            scene='home';selected='first';restarts=0
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if label=='select_saved_role' then scene='home';return true end
                return tap(c,f,label)
            end
            runApp=function() restarts=restarts+1;selected='second';scene='entry' end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)

    def test_slow_role_connection_settles_before_identity_is_checked(self):
        self.lua.execute('''
            scene='home';selected='first';connection_ticks=0;restarts=0
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if label=='select_saved_role' then scene='connecting';return true end
                return tap(c,f,label)
            end
            local wait=require('common.device').wait
            require('common.device').wait=function(predicate,timeout)
                if scene~='connecting' then return wait(predicate,timeout) end
                for _=1,timeout do
                    if predicate() then return true end
                    connection_ticks=connection_ticks+1
                    if connection_ticks==15 then scene='home';selected='second' end
                end
                return false
            end
            runApp=function() restarts=restarts+1 end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().connection_ticks,15)
        self.assertEqual(self.lua.globals().restarts,0)

    def test_unresolved_role_connection_stops_without_restarting_or_verifying(self):
        self.lua.execute('''
            scene='home';selected='first';restarts=0
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if label=='select_saved_role' then scene='connecting';return true end
                return tap(c,f,label)
            end
            runApp=function() restarts=restarts+1 end
        ''')
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(bool(self.lua.globals().ctx.identity_verified))
        self.assertEqual(self.lua.globals().restarts,0)

    def test_restarted_login_disappearing_after_wait_is_not_accepted(self):
        self.lua.execute('''
            scene='settings';blocked_settings=true;entry_reads=0
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                if f.kind=='entry' then
                    entry_reads=entry_reads+1
                    return scene=='entry' and entry_reads==1
                end
                return present(f)
            end
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if f.kind=='entry' then return false end
                return tap(c,f,label)
            end
        ''')
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(bool(self.lua.globals().ctx.identity_verified))
        self.assertEqual(self.lua.globals().logs[len(self.lua.globals().logs)][2],
                         'pocket_entry_not_actionable')

    def test_restarted_login_retries_only_targets_that_changed_before_input(self):
        self.lua.execute('''
            scene='settings';blocked_settings=true;entry_attempts=0;selected='second'
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if f.kind=='entry' then
                    entry_attempts=entry_attempts+1
                    if entry_attempts<3 then return false end
                end
                return tap(c,f,label)
            end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertEqual(self.lua.globals().entry_attempts,3)
        self.assertEqual(list(self.lua.globals().taps.values()).count('pocket_entry'),1)
        self.assertTrue(self.lua.globals().ctx.identity_verified)

    def test_entry_waits_for_portrait_capture_after_confirmation(self):
        self.lua.execute('''
            scene='entry';selected='second';portrait_refreshes=0
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if f.kind=='confirm' then
                    taps[#taps+1]=label;scene='rotating';return true
                end
                assert(scene~='rotating','navigation before portrait was verified')
                return tap(c,f,label)
            end
            resetScreen=function()
                if scene=='rotating' then
                    portrait_refreshes=portrait_refreshes+1
                    if portrait_refreshes==2 then scene='home' end
                end
            end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertEqual(self.lua.globals().portrait_refreshes,2)
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(list(self.lua.globals().taps.values()),['pocket_entry','pocket_confirm'])

    def test_returned_login_refreshes_session_once_and_rechecks_identity(self):
        self.lua.execute('''
            scene='entry';selected='second';restarts=0
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if f.kind=='confirm' and restarts==0 then
                    taps[#taps+1]=label;scene='entry';return true
                end
                return tap(c,f,label)
            end
            runApp=function() restarts=restarts+1;scene='entry' end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)

    def test_persistent_return_to_login_stops_after_one_restart(self):
        self.lua.execute('''
            scene='entry';ctx.identity_verified=true;restarts=0
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if f.kind=='confirm' then
                    taps[#taps+1]=label;scene='entry';return true
                end
                return tap(c,f,label)
            end
            runApp=function() restarts=restarts+1;scene='entry' end
        ''')
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,1)

    def test_entry_stops_when_portrait_destination_never_loads(self):
        self.lua.execute('''
            scene='entry'
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if f.kind=='confirm' then
                    taps[#taps+1]=label;scene='rotating';return true
                end
                assert(scene~='rotating','navigation before portrait was verified')
                return tap(c,f,label)
            end
        ''')
        self.assertFalse(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertFalse(bool(self.lua.globals().ctx.identity_verified))
        self.assertEqual(self.lua.globals().logs[len(self.lua.globals().logs)][2],
                         'pocket_home_not_verified')
        self.assertEqual(list(self.lua.globals().taps.values()),['pocket_entry','pocket_confirm'])

    def test_entry_rejects_partial_home_until_upper_role_control_is_visible(self):
        self.lua.execute('''
            scene='entry';selected='second';portrait_refreshes=0
            local tap=require('common.device').tap
            require('common.device').tap=function(c,f,label)
                if f.kind=='confirm' then
                    taps[#taps+1]=label;scene='partial_home';return true
                end
                assert(scene~='partial_home','role navigation on an incomplete portrait frame')
                return tap(c,f,label)
            end
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                if f.kind=='home' and scene=='partial_home' then return true end
                return present(f)
            end
            resetScreen=function()
                if scene=='partial_home' then
                    portrait_refreshes=portrait_refreshes+1
                    if portrait_refreshes==3 then scene='home' end
                end
            end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertEqual(self.lua.globals().portrait_refreshes,3)
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(list(self.lua.globals().taps.values()),['pocket_entry','pocket_confirm'])

    def test_incident_close_requires_verified_disappearance(self):
        self.lua.execute("""
            scene='home';incident_visible=true
            require('common.device').tap=function(c,f,label)
                taps[#taps+1]=label;return true
            end
        """)
        self.assertFalse(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['close_incident_notice'])

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

    def test_hidden_saved_role_uses_bounded_shared_scanner_before_switch(self):
        self.lua.execute('''
            scene='home';missing_selector='second';scans=0
            package.preload['common.list_navigation']=function() return {
                find=function(c,spec)
                    scans=scans+1
                    assert(spec.max_forward==6 and spec.valid() and spec.inspect()==nil)
                    missing_selector=nil
                    return spec.inspect()
                end
            } end
        ''')
        self.assertTrue(self.module.prepare_recorded(self.lua.globals().ctx))
        self.assertEqual(self.lua.globals().scans,1)
        self.assertEqual(self.lua.globals().selected,'second')

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

    def test_shimen_retry_can_rest_before_switching_roles(self):
        self.lua.execute('''
            scene='puzzle_retry'
            package.preload['tasks.dungeon.pages']=function() return {state=function() return 'unknown' end} end
            package.preload['tasks.zhuagui.pages']=function() return {state=function() return 'task_list' end} end
            package.preload['tasks.shimen.pages']=function() return {state=function() return scene end} end
            require('common.device').tap=function(c,f,label,guard)
                assert(guard())
                taps[#taps+1]=label
                scene='home';return true
            end
        ''')
        self.assertTrue(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),['shimen_rest_before_identity_check'])

    def test_shimen_retry_rest_requires_verified_destination(self):
        self.lua.execute('''
            scene='puzzle_retry'
            package.preload['tasks.dungeon.pages']=function() return {state=function() return 'unknown' end} end
            package.preload['tasks.zhuagui.pages']=function() return {state=function() return 'unknown' end} end
            package.preload['tasks.shimen.pages']=function() return {state=function() return scene end} end
        ''')
        self.assertFalse(self.module.return_home(self.lua.globals().ctx))

    def test_shimen_rest_returns_via_home_tab_without_canceling_task(self):
        self.lua.execute('''
            scene='puzzle_retry'
            package.preload['tasks.dungeon.pages']=function() return {state=function() return 'unknown' end} end
            package.preload['tasks.zhuagui.pages']=function() return {state=function() return 'task_list' end} end
            package.preload['tasks.shimen.pages']=function() return {state=function() return scene end} end
            require('common.device').tap=function(c,f,label,guard)
                assert(guard())
                taps[#taps+1]=label
                if label=='shimen_rest_before_identity_check' then scene='catch'
                elseif label=='shimen_home_without_cancel' then scene='home'
                else error('unexpected navigation') end
                return true
            end
        ''')
        self.assertTrue(self.module.return_home(self.lua.globals().ctx))
        self.assertEqual(list(self.lua.globals().taps.values()),
                         ['shimen_rest_before_identity_check','shimen_home_without_cancel'])

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


class LoginTimingTest(unittest.TestCase):
    """Use production polling and input revalidation with a virtual device clock."""

    def setUp(self):
        RoleNavigationTest.setUp(self)
        self.lua.execute('''
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                if capture_hook then capture_hook(label) end
            end} end
        ''')
        production=self.lua.execute((ROOT/'src/common/device.lua').read_text(encoding='utf-8'))
        self.lua.globals().production_wait=production.wait
        self.lua.globals().production_tap=production.tap
        self.lua.execute('''
            scene='entry';selected='second';clock=0;restarts=0;native_taps={};refreshes={};direction=0
            ctx.profile={clock=function() return clock end}
            local device=require('common.device')
            device.wait=production_wait;device.tap=production_tap
            init=function(value) direction=value end
            resetScreen=function() refreshes[#refreshes+1]=clock end
            mSleep=function(ms)
                clock=clock+ms
                if scene=='splash' and entry_at and clock>=entry_at then scene='entry' end
                if scene=='waiting_confirm' and confirm_at and clock>=confirm_at then scene='confirm' end
                if scene=='rotating' and home_at and clock>=home_at then scene='home' end
                if scene=='connecting' and home_at and clock>=home_at then scene='home' end
                if time_hook then time_hook() end
            end
            runApp=function() restarts=restarts+1;scene='entry' end
            package.preload['common.assets.server_list_network_error']=function() return {kind='server_error'} end
            local detector=require('common.detector')
            local present,find=detector.present,detector.find
            detector.present=function(f)
                if f.kind=='entry' or f.kind=='confirm' or f.kind=='server_error' then
                    return direction==1 and scene==f.kind
                end
                if f.kind=='home_tab' then return direction==0 and scene=='task_list' end
                return direction==0 and present(f)
            end
            detector.find=function(f)
                if lose_next_target==f.kind then lose_next_target=nil;return nil end
                local x=({entry=100,confirm=200,home_tab=300})[f.kind]
                if f.kind=='selector' then x=f.alias=='second' and 400 or 401 end
                if x then
                    if detector.present(f) then return {x=x,y=100,tap_offset={0,0}} end
                    return nil
                end
                return find(f)
            end
            tap=function(x,y)
                native_taps[#native_taps+1]={x=x,y=y,clock=clock,direction=direction}
                if x==100 then
                    confirm_at=confirmation_delay and clock+confirmation_delay
                    scene=confirmation_delay and 'waiting_confirm' or 'confirm'
                elseif x==200 then
                    home_at=rotation_delay and clock+rotation_delay
                    scene=rotation_delay and 'rotating' or 'home'
                elseif x==300 then scene='home'
                elseif x==400 then
                    selected='second';home_at=connection_delay and clock+connection_delay
                    scene=connection_delay and 'connecting' or 'home'
                else error('unexpected native input') end
                if tap_hook then tap_hook(x) end
            end
        ''')

    def run_prepare(self):
        return self.module.prepare_recorded(self.lua.globals().ctx)

    def native_points(self):
        return [tap.x for tap in self.lua.globals().native_taps.values()]

    def last_reason(self):
        logs=self.lua.globals().logs
        return logs[len(logs)][2]

    def test_first_login_frame_miss_is_reprobed_before_native_input(self):
        self.lua.execute('''
            scene='splash';entry_at=500
            package.preload['tasks.dungeon.pages']=function() return {state=function() return 'unknown' end} end
            package.preload['tasks.zhuagui.pages']=function() return {state=function() return 'task_list' end} end
            package.preload['common.assets.home_tab']=function() return {kind='home_tab'} end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.native_points(),[100,200])
        self.assertEqual(self.lua.globals().native_taps[1].clock,1500)
        self.assertEqual(self.lua.globals().restarts,0)
        self.assertTrue(self.lua.globals().ctx.identity_verified)

    def test_unknown_page_times_out_without_input_or_identity(self):
        self.lua.execute("scene='unknown';ctx.identity_verified=true")
        self.assertFalse(self.run_prepare())
        self.assertEqual(self.native_points(),[])
        self.assertEqual(self.lua.globals().clock,60000)
        self.assertEqual(self.lua.globals().restarts,0)
        self.assertFalse(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.last_reason(),'pocket_entry_not_verified')

    def test_verified_home_has_no_login_wait_or_input(self):
        self.lua.execute("scene='home'")
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.lua.globals().clock,0)
        self.assertEqual(self.native_points(),[])

    def test_initial_partial_home_waits_for_upper_role_control(self):
        self.lua.execute('''
            scene='partial_home'
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                if scene=='partial_home' and f.kind=='home' then return direction==0 end
                return present(f)
            end
            time_hook=function() if clock>=1500 then scene='home' end end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.lua.globals().clock,1500)
        self.assertEqual(self.native_points(),[])

    def test_visible_home_identity_cannot_bypass_failed_overlay_cleanup(self):
        self.lua.execute('''
            scene='home';ctx.identity_verified=true
            local rewards=require('tasks.rewards.pages')
            rewards.features.bonus_receipt={kind='bonus_receipt'}
            rewards.close_receipt=function() return false end
            local present=require('common.detector').present
            require('common.detector').present=function(f)
                return f.kind=='bonus_receipt' or present(f)
            end
        ''')
        self.assertFalse(self.run_prepare())
        self.assertFalse(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.native_points(),[])
        self.assertEqual(self.last_reason(),'return_home_not_verified')

    def test_selected_role_slow_connection_is_awaited_before_home_cleanup(self):
        self.lua.execute("scene='picker';selected='first';connection_delay=12000")
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.native_points(),[400])
        self.assertGreaterEqual(self.lua.globals().clock,17000)
        self.assertTrue(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.lua.globals().restarts,0)

    def test_picker_can_finish_loading_without_login_wait(self):
        self.lua.execute('''
            scene='picker'
            time_hook=function() if clock>=1000 then scene='home' end end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.lua.globals().clock,1000)
        self.assertEqual(self.native_points(),[])

    def test_failed_saved_role_selection_clears_previous_identity(self):
        self.lua.execute('''
            scene='picker';ctx.identity_verified=true
            local original=loadfile
            loadfile=function(path)
                if path:match('daily_selector_') then return nil end
                return original(path)
            end
        ''')
        self.assertFalse(self.run_prepare())
        self.assertFalse(self.lua.globals().ctx.identity_verified)
        self.assertEqual(self.native_points(),[])

    def test_known_task_returns_home_without_login_wait(self):
        self.lua.execute('''
            scene='task_list'
            package.preload['tasks.dungeon.pages']=function() return {state=function() return 'unknown' end} end
            package.preload['tasks.zhuagui.pages']=function() return {state=function() return scene end} end
            package.preload['common.assets.home_tab']=function() return {kind='home_tab'} end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.native_points(),[300])
        self.assertEqual(self.lua.globals().clock,1200)

    def test_confirmation_after_thirty_seconds_is_accepted_with_fresh_capture(self):
        self.lua.execute('''
            confirmation_delay=45000
            capture_hook=function(label)
                if label=='pocket_confirm_before' then
                    assert(direction==1 and refreshes[#refreshes]==clock,'stale confirmation capture')
                end
            end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.native_points(),[100,200])
        self.assertGreaterEqual(self.lua.globals().native_taps[2].clock,45000)
        self.assertEqual(self.lua.globals().restarts,0)

    def test_visible_entry_waits_for_loading_to_clear_and_stay_clear(self):
        self.lua.execute('''
            entry_loading=true
            time_hook=function() entry_loading=clock<2000 or clock==2500 end
            tap_hook=function(x) if x==100 then assert(not entry_loading) end end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.native_points(),[100,200])
        self.assertEqual(self.lua.globals().native_taps[1].clock,4000)

    def test_loading_return_during_capture_prevents_entry_input(self):
        self.lua.execute('''
            capture_hook=function(label)
                if label=='pocket_entry_before' and not changed then
                    changed=true;entry_loading=true
                end
            end
            time_hook=function() if clock>=3000 then entry_loading=false end end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.native_points(),[100,200])
        self.assertEqual(self.lua.globals().native_taps[1].clock,4000)

    def assert_revalidation_retry(self,kind):
        self.lua.globals().changed_kind=kind
        self.lua.execute('''
            capture_hook=function(label)
                if not changed and label=='pocket_'..changed_kind..'_before' then
                    changed=true;lose_next_target=changed_kind
                end
            end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.native_points(),[100,200])
        self.assertEqual(self.lua.globals().clock,3900)
        self.assertEqual(self.lua.globals().restarts,0)
        self.assertEqual(sum(row[1]=='tap_skipped' for row in self.lua.globals().logs.values()),1)

    def test_entry_target_can_change_before_input_and_be_retried(self):
        self.assert_revalidation_retry('entry')

    def test_confirmation_target_can_change_before_input_and_be_retried(self):
        self.assert_revalidation_retry('confirm')

    def test_sent_entry_input_is_not_repeated_during_confirmation_wait(self):
        self.lua.execute('''
            ctx.pocket_entry_recovered=true
            tap_hook=function(x) if x==100 then scene='entry' end end
        ''')
        self.assertFalse(self.run_prepare())
        self.assertEqual(self.native_points(),[100])
        self.assertEqual(self.lua.globals().clock,62200)
        self.assertEqual(self.last_reason(),'pocket_entry_transition_not_verified')

    def test_sent_confirmation_input_is_not_repeated_during_home_wait(self):
        self.lua.execute("tap_hook=function(x) if x==200 then scene='confirm' end end")
        self.assertFalse(self.run_prepare())
        self.assertEqual(self.native_points(),[100,200])
        self.assertEqual(self.lua.globals().clock,63400)
        self.assertEqual(self.last_reason(),'pocket_home_not_verified')

    def test_async_rotation_waits_for_home_without_extra_input(self):
        self.lua.execute('''
            rotation_delay=12000
            capture_hook=function(label)
                if label=='pocket_confirm_before' then assert(direction==1) end
            end
        ''')
        self.assertTrue(self.run_prepare())
        self.assertEqual(self.native_points(),[100,200])
        self.assertGreaterEqual(self.lua.globals().clock,13200)
        self.assertEqual(self.lua.globals().direction,0)

    def test_network_error_during_entry_wait_stops_without_input(self):
        self.lua.execute("scene='splash';time_hook=function() if clock>=1500 then scene='server_error' end end")
        self.assertFalse(self.run_prepare())
        self.assertEqual(self.native_points(),[])
        self.assertEqual(self.lua.globals().clock,1500)
        self.assertEqual(self.last_reason(),'server_list_network_error')

    def test_network_error_during_confirmation_wait_stops_before_confirmation(self):
        self.lua.execute('''
            confirmation_delay=15000
            time_hook=function() if clock>=2500 then scene='server_error' end end
        ''')
        self.assertFalse(self.run_prepare())
        self.assertEqual(self.native_points(),[100])
        self.assertLess(self.lua.globals().clock,3000)
        self.assertEqual(self.last_reason(),'server_list_network_error')


if __name__=='__main__': unittest.main()
