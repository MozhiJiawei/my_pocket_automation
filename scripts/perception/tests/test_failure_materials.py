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
