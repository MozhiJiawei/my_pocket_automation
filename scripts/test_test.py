"""Task selection must partition the full regression without losing checks."""
from unittest import TestCase,TestSuite
from unittest.mock import patch
from scripts import test as runner
from tests.perception import test_corpus as corpus


class TestGroupsTest(TestCase):
    def test_four_groups_are_disjoint_and_cover_all_discovered_tests(self):
        discovered=TestSuite([runner.production_suite(),runner.tooling_suite()])
        original=list(runner.flatten(discovered))
        self.assertTrue(set(runner.METHOD_GROUPS).issubset({test.id() for test in original}))
        grouped={group:[*runner.flatten(runner.select_tests(discovered,[group])),
                        *runner.flatten(runner.select_tests(discovered,[group],recognition=True))]
                 for group in runner.GROUPS}
        ids=[test.id() for tests in grouped.values() for test in tests]
        self.assertEqual(len(ids),len(set(ids)))
        # Two formerly combined corpus checks are each split into three tasks.
        self.assertEqual(len(ids),len(original)+4)
        self.assertEqual({test.id() for test in original if test.id() not in runner.CORPUS_IDS},
                         {identity for identity in ids if '[' not in identity})
        for group,tests in grouped.items():
            self.assertTrue(tests,group)
            self.assertTrue(all(runner.test_group(test)==group for test in tests))
        self.assertFalse(list(runner.flatten(runner.select_tests(discovered,['other'],recognition=True))))

    def test_partial_corpus_validation_only_loads_selected_task(self):
        for task in runner.GROUPS[:3]:
            with self.subTest(task=task),patch('tests.perception.test_corpus.load_cases',return_value=[]) as load:
                corpus.CorpusTest('test_annotations_and_evidence_are_consistent',task).test_annotations_and_evidence_are_consistent()
                load.assert_called_once_with(task)

    def test_partial_recognition_cannot_evaluate_another_tasks_frames(self):
        for task in runner.GROUPS[:3]:
            with self.subTest(task=task),patch('tests.perception.test_corpus.load_cases',return_value=[]) as load, \
                 patch('tests.perception.test_corpus.evaluate_inputs',return_value=([],[])) as evaluate, \
                 patch('tests.perception.test_corpus.write_report') as report,patch('builtins.print'):
                corpus.CorpusTest('test_reviewed_recognition_and_planned_coordinates',task).test_reviewed_recognition_and_planned_coordinates()
                load.assert_called_once_with(task)
                evaluate.assert_called_once_with([])
                self.assertEqual(report.call_args.args[2].name,task)

    def test_failed_discovery_is_not_filtered_into_an_unselected_group(self):
        from unittest import TestLoader
        failed=TestLoader().loadTestsFromName('missing_test_module_for_group_selection')
        with self.assertRaisesRegex(RuntimeError,'discovery failed'):
            runner.select_tests(failed,['shimen'])
