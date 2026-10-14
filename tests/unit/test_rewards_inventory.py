"""Production inventory keeps clicking remaining gourds until explicit empty UI."""
from pathlib import Path
import unittest

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class RewardsInventoryTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            ctx={config={step='complete'}}
            queues={}
            for _,category in ipairs({'task','dungeon','special'}) do
                queues[category]={{name=category..'_a',uses=2},
                    {name=category..'_b',uses=3},{name=category..'_c',uses=1}}
            end
            page_state='inventory'; inputs={}; entries={}; closed_types={}; captures={}; logs={}
            local function forbidden() error('inventory must not use quantity, identity, or progress interfaces') end
            package.preload['progress']=forbidden
            package.preload['common.digit_reader']=forbidden
            local function consume()
                if endless_stock then return end
                active.uses=active.uses-1
                if active.uses==0 then
                    closed_types[#closed_types+1]=active.name
                    assert(queues[category][1]==active, 'must process the first remaining row')
                    table.remove(queues[category],1)
                    active=nil;page_state='inventory'
                else
                    page_state='detail'
                end
                if unknown_after_action then page_state='unknown' end
            end
            package.preload['tasks.rewards.pages']=function() return {
                features={open_one='open_one',discard='discard',discard_confirm='discard_confirm'},
                count=forbidden,identity=forbidden,list_signature=forbidden,
                select_category=function(c,requested)
                    if category_failed or not queues[requested] then return false end
                    category=requested;active=nil;page_state=selected_state or 'inventory';return true
                end,
                empty_category=function()
                    return page_state=='inventory' and #queues[category]==0 and not missing_empty_evidence
                end,
                cards=function()
                    if cards_unknown then return nil end
                    if cards_missing then return {} end
                    local cards={}
                    for i=1,math.min(3,#queues[category]) do
                        cards[#cards+1]={kind='card',gourd=queues[category][i]}
                    end
                    return cards
                end,
                state=function() return page_state end
            } end
            package.preload['common.detector']=function() return {
                present=function(feature)
                    return page_state=='detail' and not missing_action_button and
                        feature==(category=='special' and 'discard' or 'open_one')
                end
            } end
            package.preload['common.device']=function() return {
                tap=function(c,feature,label)
                    if type(feature)=='table' then
                        assert(page_state=='inventory' and feature.gourd==queues[category][1],
                            'card must be the first visible remaining row')
                        entries[#entries+1]=feature.gourd.name
                        if entry_failed then return false end
                        active=feature.gourd
                        if not entry_stuck then page_state='detail' end
                        return true
                    end
                    inputs[#inputs+1]={button=feature,label=label,gourd=active and active.name}
                    if feature=='discard_confirm' then
                        assert(page_state=='discard_confirm', 'confirmation must be visible')
                        if confirmation_failed then return false end
                        if not confirmation_stuck then consume() end
                        return true
                    end
                    assert(page_state=='detail', 'business action requires detail')
                    assert(feature==(category=='special' and 'discard' or 'open_one'),
                        'special must never open; task and dungeon must never discard')
                    if action_failed then return false end
                    if unexpected_confirmation or (category=='special' and confirmation_enabled) then
                        page_state='discard_confirm'
                    else
                        consume()
                    end
                    return true
                end,
                wait=function(predicate,attempts)
                    for _=1,attempts do if predicate() then return true end end
                    return false
                end,
                swipe=function() error('first-row loop must not scroll') end
            } end
            package.preload['dfx.log']=function() return {
                write=function(c,event,text) logs[#logs+1]={event=event,text=text} end
            } end
            package.preload['dfx.snapshot']=function() return {
                capture=function(c,reason) captures[#captures+1]=reason end
            } end
        ''')
        self.inventory = self.lua.eval("require('tasks.rewards.inventory')")[0]
        self.globals = self.lua.globals()

    def clear(self, category='task'):
        return self.inventory.clear(self.globals.ctx, category)

    def assert_paused(self, result, reason):
        self.assertEqual((result['status'], result['reason']), ('paused', reason))
        self.assertEqual(self.globals.captures[len(self.globals.captures)], reason)

    def input_buttons(self):
        return [entry['button'] for entry in self.globals.inputs.values()]

    def test_all_categories_continue_through_multiple_types_until_explicit_empty(self):
        for category in ('task', 'dungeon', 'special'):
            with self.subTest(category=category):
                self.setUp()
                result = self.clear(category)
                self.assertEqual((result['status'], result['reason']), ('done', 'category_empty'))
                self.assertEqual(len(self.globals.queues[category]), 0)
                self.assertEqual(self.globals.page_state, 'inventory')
                button = 'discard' if category == 'special' else 'open_one'
                self.assertEqual(self.input_buttons(), [button] * 6)
                self.assertEqual(list(self.globals.entries.values()),
                                 [f'{category}_a', f'{category}_b', f'{category}_c'])
                self.assertEqual(self.globals.logs[1]['event'], 'rewards_category_empty')

    def test_last_gourd_closes_popup_and_opens_the_next_remaining_row(self):
        result = self.clear('dungeon')
        self.assertEqual(result['status'], 'done')
        self.assertEqual([entry['gourd'] for entry in self.globals.inputs.values()],
                         ['dungeon_a', 'dungeon_a', 'dungeon_b', 'dungeon_b', 'dungeon_b', 'dungeon_c'])
        self.assertEqual(list(self.globals.closed_types.values()),
                         ['dungeon_a', 'dungeon_b', 'dungeon_c'])
        self.assertEqual(list(self.globals.entries.values()),
                         ['dungeon_a', 'dungeon_b', 'dungeon_c'])

    def test_special_only_discards_with_no_open_input(self):
        result = self.clear('special')
        self.assertEqual(result['status'], 'done')
        self.assertEqual(self.input_buttons(), ['discard'] * 6)
        self.assertTrue(all(entry['label'] == 'rewards_discard'
                            for entry in self.globals.inputs.values()))

    def test_special_confirmation_finishes_each_discard_and_continues(self):
        self.globals.confirmation_enabled = True
        result = self.clear('special')
        self.assertEqual((result['status'], result['reason']), ('done', 'category_empty'))
        self.assertEqual(self.input_buttons(), ['discard', 'discard_confirm'] * 6)
        self.assertEqual(len(self.globals.queues.special), 0)
        self.assertEqual(len(self.globals.entries), 3)

    def test_advance_performs_one_business_action_then_pauses(self):
        for category, reason in (('task', 'opened_one_gourd'),
                                 ('dungeon', 'opened_one_gourd'),
                                 ('special', 'discarded_one_special')):
            with self.subTest(category=category):
                self.setUp()
                self.globals.ctx.config.step = 'advance'
                result = self.clear(category)
                self.assertEqual((result['status'], result['reason']), ('paused', reason))
                self.assertEqual(len(self.globals.inputs), 1)
                self.assertEqual(len(self.globals.entries), 1)
                self.assertEqual(self.globals.page_state, 'detail')
                self.assertEqual(len(self.globals.queues[category]), 3)

    def test_advance_includes_discard_confirmation_without_starting_next_action(self):
        self.globals.ctx.config.step = 'advance'
        self.globals.confirmation_enabled = True
        result = self.clear('special')
        self.assertEqual((result['status'], result['reason']), ('paused', 'discarded_one_special'))
        self.assertEqual(self.input_buttons(), ['discard', 'discard_confirm'])
        self.assertEqual(len(self.globals.entries), 1)

    def test_empty_category_is_completed_without_opening_any_card(self):
        self.lua.execute('queues.dungeon={}')
        result = self.clear('dungeon')
        self.assertEqual((result['status'], result['reason']), ('done', 'category_empty'))
        self.assertEqual(len(self.globals.inputs), 0)
        self.assertEqual(len(self.globals.entries), 0)

    def test_absent_cards_without_positive_empty_evidence_cannot_complete(self):
        self.lua.execute('queues.dungeon={};missing_empty_evidence=true')
        self.assert_paused(self.clear('dungeon'), 'rewards_gourd_entry_not_verified')
        self.assertEqual(len(self.globals.inputs), 0)

    def test_unrecognized_cards_stop_before_any_business_action(self):
        for flag in ('cards_unknown', 'cards_missing'):
            with self.subTest(flag=flag):
                self.setUp()
                self.globals[flag] = True
                self.assert_paused(self.clear(), 'rewards_gourd_entry_not_verified')
                self.assertEqual(len(self.globals.inputs), 0)
                self.assertEqual(len(self.globals.entries), 0)

    def test_entry_click_or_detail_wait_failure_stops(self):
        for flag in ('entry_failed', 'entry_stuck'):
            with self.subTest(flag=flag):
                self.setUp()
                self.globals[flag] = True
                self.assert_paused(self.clear(), 'rewards_gourd_entry_not_verified')
                self.assertEqual(len(self.globals.inputs), 0)
                self.assertEqual(len(self.globals.entries), 1)

    def test_unknown_page_after_selection_stops_before_any_input(self):
        self.globals.selected_state = 'unknown'
        self.assert_paused(self.clear(), 'rewards_page_not_verified')
        self.assertEqual(len(self.globals.inputs), 0)
        self.assertEqual(len(self.globals.entries), 0)

    def test_category_selection_failure_stops(self):
        self.globals.category_failed = True
        self.assert_paused(self.clear(), 'rewards_category_not_verified')
        self.assertEqual(len(self.globals.inputs), 0)

    def test_invalid_category_is_rejected_by_page_selection(self):
        self.assert_paused(self.clear('unknown'), 'rewards_category_not_verified')
        self.assertEqual(len(self.globals.inputs), 0)

    def test_action_target_failure_stops_without_retry(self):
        self.globals.action_failed = True
        self.assert_paused(self.clear(), 'rewards_action_not_verified')
        self.assertEqual(self.input_buttons(), ['open_one'])

    def test_unknown_action_result_stops_without_starting_next_item(self):
        self.globals.unknown_after_action = True
        self.assert_paused(self.clear(), 'rewards_action_result_not_verified')
        self.assertEqual(self.input_buttons(), ['open_one'])
        self.assertEqual(len(self.globals.entries), 1)

    def test_detail_without_available_action_button_stops(self):
        self.globals.missing_action_button = True
        self.assert_paused(self.clear(), 'rewards_action_result_not_verified')
        self.assertEqual(self.input_buttons(), ['open_one'])

    def test_open_action_cannot_accept_a_discard_confirmation(self):
        self.globals.unexpected_confirmation = True
        self.assert_paused(self.clear(), 'rewards_discard_confirmation_not_verified')
        self.assertEqual(self.input_buttons(), ['open_one'])

    def test_failed_or_unresolved_discard_confirmation_stops(self):
        for flag in ('confirmation_failed', 'confirmation_stuck'):
            with self.subTest(flag=flag):
                self.setUp()
                self.globals.confirmation_enabled = True
                self.globals[flag] = True
                self.assert_paused(self.clear('special'), 'rewards_discard_confirmation_not_verified')
                self.assertEqual(self.input_buttons(), ['discard', 'discard_confirm'])
                self.assertEqual(len(self.globals.entries), 1)

    def test_loop_is_bounded_when_a_gourd_never_disappears(self):
        self.globals.endless_stock = True
        self.assert_paused(self.clear(), 'rewards_loop_limit_reached')
        self.assertEqual(self.input_buttons(), ['open_one'] * 200)
        self.assertEqual(len(self.globals.entries), 1)

    def test_clearing_does_not_load_progress_or_quantity_readers(self):
        for category in ('task', 'dungeon', 'special'):
            result = self.clear(category)
            self.assertEqual(result['status'], 'done')
        self.assertIsNone(self.lua.eval("package.loaded['progress']"))
        self.assertIsNone(self.lua.eval("package.loaded['common.digit_reader']"))
        self.assertEqual(set(self.globals.ctx), {'config'})


if __name__ == '__main__':
    unittest.main()
