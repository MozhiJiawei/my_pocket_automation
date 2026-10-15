"""Run selected task groups, or the full pre-merge regression within 60 seconds."""
import argparse
from pathlib import Path
import sys
import time
import unittest
import io
from concurrent.futures import ProcessPoolExecutor
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class TimedResult(unittest.TextTestResult):
    """Keep test costs visible without rerunning or changing the assertions."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.timings=[]
    def startTest(self,test):
        self.started=time.perf_counter();super().startTest(test)
    def stopTest(self,test):
        self.timings.append((time.perf_counter()-self.started,test.id()))
        super().stopTest(test)


GROUPS=('zhuagui','dungeon','shimen','other')
GROUP_NAMES={'zhuagui':'抓鬼','dungeon':'副本','shimen':'师门','other':'其他'}
ALIASES={**{group:group for group in GROUPS},**{name:group for group,name in GROUP_NAMES.items()},'all':'all','全量':'all'}
CORPUS_PREFIX='tests.perception.test_corpus.CorpusTest.'
CORPUS_METHODS=('test_annotations_and_evidence_are_consistent','test_reviewed_recognition_and_planned_coordinates')
RECOGNITION_METHOD=CORPUS_METHODS[1]
CORPUS_IDS={CORPUS_PREFIX+method for method in CORPUS_METHODS}

# Shared infrastructure belongs to other. Mixed modules use method overrides;
# new task-specific modules must be assigned here rather than silently omitted.
MODULE_GROUPS={
    'tests.unit.test_shimen_guards':'shimen',
    'tests.unit.test_shimen_puzzles':'shimen',
    'tests.unit.test_zhuagui_legacy':'zhuagui',
    'tests.unit.test_zhuagui_guards':'zhuagui',
    'tests.unit.test_zhuagui_catalog':'zhuagui',
    'tests.unit.test_puzzle_swaps':'zhuagui',
    'tests.unit.test_find_frame_guard':'zhuagui',
    'tests.perception.test_task_entry':'zhuagui',
    'tests.replay.test_frame_sequences':'zhuagui',
    'tests.unit.test_dungeon_stages':'dungeon',
    'tests.unit.test_dungeon_guards':'dungeon',
    'tests.perception.test_dungeon_cards':'dungeon',
    'scripts.perception.tests.test_shimen_collection':'shimen',
    'scripts.perception.tests.test_task_review':'zhuagui',
    'scripts.perception.tests.test_puzzle_review':'zhuagui',
    'scripts.perception.tests.test_truth_contract':'zhuagui',
    'scripts.perception.tests.test_round_truth':'zhuagui',
}
METHOD_GROUPS={
    CORPUS_PREFIX+'test_shimen_frozen_scope_and_all_positive_scoring':'shimen',
    CORPUS_PREFIX+'test_required_topics_are_not_filled_with_unreviewed_objects':'zhuagui',
    'scripts.perception.tests.test_augmentation.AugmentationTest.test_shimen_transforms_every_approved_region_together':'shimen',
    'scripts.perception.tests.test_augmentation.AugmentationTest.test_approved_crop_geometry_and_parent_split':'zhuagui',
    'scripts.perception.tests.test_augmentation.AugmentationTest.test_pending_regions_never_create_variants':'zhuagui',
    'scripts.perception.tests.test_augmentation.AugmentationTest.test_puzzle_permutations_preserve_pixels_and_canonical_answer':'zhuagui',
    'scripts.perception.tests.test_round_truth.RoundTruthTest.test_shimen_requires_every_positive_and_keeps_negative_failures':'shimen',
    **{'tests.unit.test_dfx_device_failures.DeviceDiagnosticsTest.'+method:'zhuagui' for method in (
        'test_owned_ghost_recovery_allows_existing_dialogue_only','test_owned_sampling_can_resume_free_dialogue_without_identity',
        'test_sampling_recovers_visible_dialogue_without_old_state','test_ghost_recovers_visible_dialogue_without_old_state')},
    **{'tests.unit.test_role_navigation.RoleNavigationTest.'+method:'zhuagui' for method in (
        'test_quota_dialogue_closes_before_returning_home','test_quota_dialogue_with_unverified_close_cannot_reach_home')},
    **{'tests.unit.test_role_navigation.RoleNavigationTest.'+method:'dungeon' for method in (
        'test_restore_switch_only_cancels_then_verifies_list','test_restore_switch_stops_if_cancel_does_not_reach_list')},
    **{'tests.unit.test_dfx_runner.RuntimeResultTest.'+method:'zhuagui' for method in (
        'test_isolated_zhuagui_entry_checks_selected_task','test_zhuagui_observation_is_read_only_result')},
}


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


def test_group(test):
    if test.__class__.__module__=='tests.perception.test_corpus' and getattr(test,'task',None):return test.task
    if test.id() in METHOD_GROUPS:return METHOD_GROUPS[test.id()]
    if test.__class__.__module__=='tests.perception.test_find_items' and test._testMethodName.startswith('test_shimen_'):return 'shimen'
    return MODULE_GROUPS.get(test.__class__.__module__,'other')


def select_tests(suite,groups,recognition=False):
    selected=unittest.TestSuite()
    for test in flatten(suite):
        if test.__class__.__module__=='unittest.loader':raise RuntimeError('Test discovery failed: '+str(test))
        if test.id() in CORPUS_IDS:
            from tests.perception.test_corpus import CorpusTest
            candidates=[CorpusTest(test._testMethodName,task) for task in GROUPS[:3]]
        else:candidates=[test]
        for candidate in candidates:
            is_recognition=candidate.__class__.__module__=='tests.perception.test_corpus' and candidate._testMethodName==RECOGNITION_METHOD
            if test_group(candidate) in groups and is_recognition==recognition:selected.addTest(candidate)
    return selected


def production_suite():
    return unittest.TestLoader().discover(str(ROOT/'tests'),top_level_dir=str(ROOT))


def tooling_suite():
    # Separate process: tooling tests patch evaluator methods and must not
    # change the production suite's runtime while both suites run.
    suite=unittest.TestLoader().discover(str(ROOT/'scripts/perception/tests'),top_level_dir=str(ROOT))
    suite.addTests(unittest.TestLoader().discover(str(ROOT/'annotation-web'),pattern='test_*.py'))
    suite.addTests(unittest.TestLoader().loadTestsFromName('scripts.test_test'))
    return suite


def run_captured(suite):
    output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=1,resultclass=TimedResult).run(suite)
    for elapsed,name in sorted(result.timings,reverse=True)[:3]:
        output.write(f'{elapsed:.3f}s {name}\n')
    return result.testsRun,result.wasSuccessful(),output.getvalue()


def tooling_tests(groups):
    import cv2
    # Match the annotation server and avoid oversubscribing the recognition
    # worker while image-geometry tooling tests run alongside it.
    cv2.setNumThreads(1)
    return run_captured(select_tests(tooling_suite(),groups))


def recognition_tests(groups):
    # Its GPU worker pool stays separate from unit-test mocks and tool patches.
    suite=unittest.TestLoader().loadTestsFromName(CORPUS_PREFIX+RECOGNITION_METHOD)
    return run_captured(select_tests(suite,groups,recognition=True))


def main():
    import cv2
    cv2.setNumThreads(1)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group','--task',nargs='+',choices=tuple(ALIASES),default=['all'],help='抓鬼/zhuagui 副本/dungeon 师门/shimen 其他/other; default: all')
    parser.add_argument('--list',action='store_true',help='List selected tests without running them')
    parser.add_argument('--max-seconds',type=float,default=60)
    args=parser.parse_args()
    if args.max_seconds<=0:parser.error('--max-seconds must be positive')
    groups=GROUPS if any(ALIASES[g]=='all' for g in args.group) else tuple(g for g in GROUPS if g in {ALIASES[a] for a in args.group})
    started=time.perf_counter()
    discovered=production_suite()
    suite=select_tests(discovered,groups)
    tools=select_tests(tooling_suite(),groups)
    recognition_suite=select_tests(discovered,groups,recognition=True)
    planned=[*flatten(suite),*flatten(tools),*flatten(recognition_suite)]
    ids=[test.id() for test in planned]
    assert len(ids)==len(set(ids)), 'A selected test must occur exactly once'
    counts=Counter(test_group(test) for test in planned)
    print('Selected: '+', '.join(f'{GROUP_NAMES[g]}={counts[g]}' for g in groups),flush=True)
    if args.list:
        for test in planned:print(f'[{GROUP_NAMES[test_group(test)]}] {test.id()}')
        return 0
    with ProcessPoolExecutor(max_workers=2) as pool:
        tooling=pool.submit(tooling_tests,groups) if tools.countTestCases() else None
        recognition=pool.submit(recognition_tests,groups) if recognition_suite.countTestCases() else None
        result=unittest.TextTestRunner(verbosity=1,resultclass=TimedResult).run(suite)
        tool_count,tool_passed,tool_log=tooling.result() if tooling else (0,True,'')
        recognition_count,recognition_passed,recognition_log=recognition.result() if recognition else (0,True,'')
    print(recognition_log,file=sys.stderr,end='')
    print(tool_log,file=sys.stderr,end='')
    for duration,name in sorted(result.timings,reverse=True)[:3]:
        print(f'{duration:.3f}s {name}',flush=True)
    elapsed=time.perf_counter()-started
    within_budget=elapsed<=args.max_seconds
    scope='All' if groups==GROUPS else '+'.join(groups)
    print(f'{scope} {result.testsRun+recognition_count+tool_count} tests: {elapsed:.3f}s; '
          f'budget {args.max_seconds:g}s: {"PASS" if within_budget else "FAIL"}',flush=True)
    return 0 if result.wasSuccessful() and recognition_passed and tool_passed and within_budget else 1


if __name__=='__main__':sys.exit(main())
