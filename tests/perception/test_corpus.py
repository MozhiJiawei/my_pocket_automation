"""Run reviewed semantic expectations, not feature names or fake click success."""
import unittest
import json
import time
from pathlib import Path
from datetime import datetime
from scripts.perception.lib.corpus import load_cases, validate_truth, read_answers
from scripts.perception.lib.evaluation import evaluate_inputs, write_report


class CorpusTest(unittest.TestCase):
    executor=None
    def __init__(self,methodName='runTest',task=None):
        super().__init__(methodName)
        self.task=task

    def id(self):
        return super().id()+(f'[{self.task}]' if self.task else '')

    def test_annotations_and_evidence_are_consistent(self):
        root=Path(__file__).resolve().parents[2]/'testdata'
        allowed={'答案.json','预期.json','格位.json'}
        for path in root.rglob('*'):
            if not path.is_file():continue
            self.assertTrue(path==root/'README.md' or path.suffix=='.png' or path.name in allowed,
                f'正式用例混入非测试文件：{path}')
            self.assertFalse({'审核依据','待审核'}&set(path.relative_to(root).parts),str(path))
        seen=set();reviewed_folders=set()
        for case in load_cases(self.task):
            self.assertTrue(case['expected']['checks'],f'用例没有回归断言：{case["id"]}')
            self.assertNotIn(case['id'],seen)
            seen.add(case['id'])
            with self.subTest(case=case['id']): validate_truth(case,*case['capture']['size'])
            parts=Path(case['image']).parts
            folder=Path(__file__).resolve().parents[2]/'testdata'/Path(case['image']).parent
            if parts[1] in ('寻物','找鬼','拼图') and folder not in reviewed_folders:
                reviewed_folders.add(folder)
                document=read_answers(folder)
                has_regions=any(locations for section in ('正确','反例') for locations in document.get(section,{}).values())
                has_assertion=any(entry.get(field) is not None for entry in document.get('预期',{}).values()
                                  for field in ('puzzle_order','puzzle_locations','target_regions','negative_regions','forbidden_actions'))
                self.assertTrue(has_regions or has_assertion,f'识别题没有批准答案：{folder}')

    def test_reviewed_recognition_and_planned_coordinates(self):
        started=time.perf_counter()
        inputs=load_cases(self.task)
        cases,results=evaluate_inputs(inputs,executor=self.executor) if self.executor is not None else evaluate_inputs(inputs)
        recognition_elapsed=time.perf_counter()-started
        for family in {c['truth']['puzzle_family']['value'] for c in cases if 'puzzle_family' in c['truth']}:
            self.assertEqual(sum(c['truth'].get('puzzle_family',{}).get('value')==family for c in cases),24,family)
        seen=set()
        for result in results:
            with self.subTest(case=result['id']):
                self.assertNotIn(result['id'],seen)
                seen.add(result['id'])
                failures=[c for c in result['checks'] if c['status']=='failed']
                self.assertFalse(failures,failures)
        output=Path(__file__).resolve().parents[2]/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'offline-evaluation'/(self.task or 'all')
        write_report(cases,results,output)
        print(f'Recognition {self.task or "all"}: {recognition_elapsed:.3f}s; report {time.perf_counter()-started-recognition_elapsed:.3f}s',flush=True)

    def test_shimen_frozen_scope_and_all_positive_scoring(self):
        cases=[c for c in load_cases('shimen') if c['truth'].get('page',{}).get('value')=='find']
        self.assertEqual(len(cases),752)
        self.assertEqual(len({c['capture']['group'] for c in cases}),109)
        self.assertEqual(len({c['truth']['question']['value']['target'] for c in cases}),22)
        self.assertTrue(all((Path(__file__).resolve().parents[2]/'testdata'/c['image']).is_file() for c in cases))

    def test_required_topics_are_not_filled_with_unreviewed_objects(self):
        required={'蛇胆酒','黄金','黄纸','书籍','书画','香','蜡烛','野鬼','牛头','马面','僵尸'}
        present={c['truth']['question']['value']['target'] for c in load_cases('zhuagui')
                 if c['truth'].get('question',{}).get('status') in {'reviewed','user_verified','device_verified'}
                 and c['truth'].get('target_regions',{}).get('value')}
        self.assertFalse(required-present, required-present)
        checked=set()
        for case in load_cases('zhuagui'):
            if any(topic in case['id'] for topic in ('/虎骨酒/','/梅花酒/','/珍露酒/','/骷髅怪/')):
                folder=Path(__file__).resolve().parents[2]/'testdata'/case['capture']['group']
                if folder in checked:continue
                checked.add(folder)
                self.assertTrue(any(locations for locations in read_answers(folder).get('正确',{}).values()),str(folder))

if __name__=='__main__': unittest.main()
