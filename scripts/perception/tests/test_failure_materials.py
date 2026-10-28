"""Use full committed originals and real row composition for failure evidence."""
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from scripts.perception.lib.corpus import load_cases, image_path
from scripts.perception.lib.task_review import rounds
from scripts.perception.lib.failure_materials import assemble


class FailureMaterialsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pages = rounds(load_cases('zhuagui'))['抓鬼/寻物/上好的兵器/第02轮']
        cls.originals = [image_path(case).read_bytes() for _, case in sorted(pages.items())]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / '20261017_010101'
        (self.archive / 'res').mkdir(parents=True)
        (self.archive / 'log').mkdir()
        self.log = self.archive / 'log' / f'daily_{self.archive.name}.log'

    def write_round(self, task='shimen', kind='find', number=1, originals=None, verified=True):
        originals = self.originals if originals is None else originals
        prefix = f'{task}_{kind}_r{number:03d}_'
        for index, content in enumerate(originals, 1):
            # Cross the filename counter's three-digit boundary deliberately.
            name = f'daily_{self.archive.name}_{998+index:03d}_{prefix}p{index:02d}.png'
            (self.archive / 'res' / name).write_bytes(content)
        with self.log.open('a', encoding='utf-8') as log:
            log.write(f'[recognition_materials] task={task} kind={kind} account=role{number} '
                      f'prefix={prefix} pages={len(originals)} from_first={str(verified).lower()} '
                      f'captured={str(verified).lower()} coverage_verified=false reason=find_icon_not_found\n')
        return prefix

    def write_profile(self, prefix, pages, task='shimen', account='role1'):
        profile = self.archive / 'log' / f'daily_{self.archive.name}_profile.log'
        profile.write_text(
            f'[daily][{self.archive.name}][profile] scope=find_failure task={task} account={account} '
            f'prefix={prefix} reason=find_icon_not_found solver_result=find_icon_not_found '
            f'page=1 phase=scan pages=1 captured=false wall_ms=1234 other_ms=34 '
            'timing=at_wall_cpu_calls\n' + '\n'.join(
                f'[daily][{self.archive.name}][profile] {page}' for page in pages) + '\n', encoding='utf-8')
        return profile

    def test_full_round_stitches_all_originals_and_still_requires_visual_review(self):
        self.write_round()
        before = {p.name: p.read_bytes() for p in (self.archive / 'res').iterdir()}
        result, = assemble(self.archive)
        self.assertEqual(result['status'], 'awaiting_visual_review')
        self.assertEqual(result['item_height'], 2760)
        self.assertEqual(len(result['images']), 7)
        with Image.open(self.archive / result['stitched']) as image:
            self.assertEqual(image.size, (900, 3295))
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.archive / 'res').iterdir()})
        self.assertEqual(list(self.archive.glob('*.json')), [])
        self.assertNotIn('failure_profile', result)

    def test_partial_failure_keeps_profile_and_links_existing_originals(self):
        prefix = self.write_round(originals=self.originals[:1], verified=False)
        original, = (self.archive / 'res').iterdir()
        profile = self.write_profile(prefix, [
            f'scope=find_page prefix={prefix} page=0 topic=黄纸 required=1 features=12 '
            'identify=0,20,0.125,1 top=20,1180,1.5,3',
            f'scope=find_page prefix={prefix} page=1 image={original.name} candidates=24 '
            'searches=12 matches=0 selected=0 state=find_item question_matches=true '
            'error=scan targets=100,600;200,800 scan=1200,0.4,0.25,2',
        ])
        result, = assemble(self.archive)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['reason'], 'capture_not_verified')
        self.assertNotIn('stitched', result)
        trace = result['failure_profile']
        self.assertEqual(trace['log'], profile.relative_to(self.archive).as_posix())
        self.assertEqual((trace['timing_unit'], trace['at_ms_origin']), ('ms', 'question_start'))
        self.assertEqual(trace['summary'], dict(task='shimen', account='role1', prefix=prefix,
                         reason='find_icon_not_found', solver_result='find_icon_not_found',
                         page=1, phase='scan', pages=1, captured=False, wall_ms=1234,
                         other_ms=34, timing='at_wall_cpu_calls'))
        first, second = trace['pages']
        self.assertEqual(first['topic'], '黄纸')
        self.assertEqual(first['features'], 12)
        self.assertNotIn('image', first)
        self.assertEqual(second['image'], result['images'][0])
        self.assertEqual(second['targets'], [[100, 600], [200, 800]])
        self.assertTrue(second['question_matches'])
        self.assertEqual(second['stages']['scan'], dict(at_ms=1200, wall_ms=0.4, cpu_ms=0.25, calls=2))

    def test_failure_before_first_snapshot_keeps_profile_without_images(self):
        prefix = self.write_round(originals=[], verified=False)
        self.write_profile(prefix, [f'scope=find_page prefix={prefix} page=0 top=0,10,0.2,1'])
        result, = assemble(self.archive)
        self.assertEqual(result['images'], [])
        self.assertEqual(result['status'], 'incomplete')
        page, = result['failure_profile']['pages']
        self.assertEqual(page['stages']['top'], dict(at_ms=0, wall_ms=10, cpu_ms=0.2, calls=1))
        self.assertNotIn('image', page)

    def test_profile_summary_must_match_task_account_and_question(self):
        prefix = self.write_round(originals=self.originals[:1], verified=False)
        for task, account, question in [('zhuagui', 'role1', prefix),
                                        ('shimen', 'role2', prefix),
                                        ('shimen', 'role1', 'shimen_find_r002_')]:
            with self.subTest(task=task, account=account, prefix=question):
                self.write_profile(question, [f'scope=find_page prefix={prefix} page=1 matches=99'],
                                   task=task, account=account)
                result, = assemble(self.archive)
                self.assertNotIn('failure_profile', result)
                self.assertEqual(result['status'], 'incomplete')

    def test_foreign_and_damaged_page_lines_do_not_pollute_the_profile(self):
        prefix = self.write_round(originals=self.originals[:1], verified=False)
        self.write_profile(prefix, [
            'scope=find_page prefix=shimen_find_r002_ page=1 matches=99',
            f'scope=find_page prefix={prefix} account=role2 page=1 matches=99',
            f'scope=find_page prefix={prefix} task=zhuagui page=1 matches=99',
            f'scope=find_page prefix={prefix} page=1 scan=0,1,nan,1',
            f'scope=find_page prefix={prefix} page=1 matches=-1',
            f'scope=find_page prefix={prefix} page=1 page=2 matches=99',
            f'scope=find_page prefix={prefix} page=8 matches=99',
            f'scope=find_page prefix={prefix} page=1 question_matches=false matches=0 scan=0,1,0.2,1',
            f'scope=find_failure prefix={prefix} task=shimen account=role2 wall_ms=broken',
            f'scope=find_page prefix={prefix} page=2 matches=99',
        ])
        result, = assemble(self.archive)
        page, = result['failure_profile']['pages']
        self.assertEqual(page['page'], 1)
        self.assertEqual(page['matches'], 0)
        self.assertFalse(page['question_matches'])
        self.assertEqual(page['stages']['scan'], dict(at_ms=0, wall_ms=1, cpu_ms=0.2, calls=1))
        self.assertEqual(result['reason'], 'capture_not_verified')

    def test_profile_image_must_already_belong_to_this_material_page(self):
        prefix = self.write_round(originals=self.originals[:2], verified=False)
        first = next((self.archive / 'res').glob('*p01.png'))
        second = next((self.archive / 'res').glob('*p02.png'))
        foreign = f'daily_{self.archive.name}_1001_shimen_find_r002_p01.png'
        self.write_profile(prefix, [
            f'scope=find_page prefix={prefix} page=0 image={first.name} top=0,1,0.1,1',
            f'scope=find_page prefix={prefix} page=1 image={foreign} matches=0',
            f'scope=find_page prefix={prefix} page=2 image={first.name} matches=0',
            f'scope=find_page prefix={prefix} page=3 image={second.name} matches=0',
        ])
        (self.archive / 'res' / foreign).write_bytes(self.originals[0])
        result, = assemble(self.archive)
        self.assertTrue(all('image' not in page for page in result['failure_profile']['pages']))
        self.assertEqual(len(result['images']), 2)
        self.assertEqual(result['status'], 'incomplete')

    def test_broken_profile_and_reused_identity_do_not_change_capture_results(self):
        prefix = self.write_round(originals=self.originals[:1], verified=False)
        profile = self.write_profile(prefix, [])
        profile.write_text(profile.read_text(encoding='utf-8').replace('wall_ms=1234', 'wall_ms=NaN'),
                           encoding='utf-8')
        result, = assemble(self.archive)
        self.assertNotIn('failure_profile', result)
        profile.write_bytes(b'\xff[profile] scope=find_failure prefix=broken\n')
        result, = assemble(self.archive)
        self.assertNotIn('failure_profile', result)
        self.write_profile(prefix, [f'scope=find_page prefix={prefix} page=1 matches=0'])
        profile.write_text(profile.read_text(encoding='utf-8') * 2, encoding='utf-8')
        result, = assemble(self.archive)
        self.assertNotIn('failure_profile', result)
        self.assertEqual(result['reason'], 'capture_not_verified')

    def test_seven_repeated_frames_do_not_count_as_the_whole_question(self):
        self.write_round(originals=[self.originals[0]] * 7)
        result, = assemble(self.archive)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['reason'], 'insufficient_unique_rows')
        self.assertNotIn('stitched', result)

    def test_missing_pages_and_another_round_cannot_be_combined(self):
        self.write_round()
        middle = next((self.archive / 'res').glob('*_p04.png'))
        middle.unlink()
        self.write_round(task='zhuagui', number=2, originals=[self.originals[3]], verified=False)
        results = assemble(self.archive)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(item['status'] == 'incomplete' for item in results))
        self.assertTrue(all('stitched' not in item for item in results))

    def test_unknown_start_or_partial_collection_is_not_promoted_by_image_height(self):
        self.write_round(verified=False)
        result, = assemble(self.archive)
        self.assertEqual(result['status'], 'incomplete')
        self.assertNotIn('stitched', result)

    def test_puzzle_keeps_one_full_original_and_rejects_cropped_or_broken_images(self):
        self.write_round(kind='puzzle', originals=[self.originals[0]])
        prefix = self.write_round(kind='puzzle', number=2, originals=[self.originals[0]])
        path = next((self.archive / 'res').glob(f'*_{prefix}p01.png'))
        Image.new('RGB', (900, 800), 'blue').save(path)
        self.write_round(kind='puzzle', number=3, originals=[b'broken png'])
        results = assemble(self.archive)
        self.assertEqual([item['status'] for item in results],
                         ['awaiting_visual_review', 'incomplete', 'incomplete'])


if __name__ == '__main__':
    unittest.main()
