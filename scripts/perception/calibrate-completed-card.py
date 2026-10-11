"""Build task-list and completed-card signatures from reviewed failure evidence."""
import importlib.util
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.perception.lib.corpus import load_cases, validate


def main():
    spec = importlib.util.spec_from_file_location('reviewed_items', Path(__file__).with_name('calibrate-reviewed-items.py'))
    sampler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sampler)
    cases = {case['id']: case for case in load_cases('zhuagui')}
    specifications = {
        'task_list_title': ('抓鬼/页面/任务列表/场景02/画面.png', 'task_list', [[50,188,185,247]]),
        'completed_card': ('抓鬼/页面/今日完成任务卡片/场景01/画面.png', 'quota_completed_card',
                           [[275,1170,358,1213], [715,1292,847,1345]]),
        'quota_dialogue': ('抓鬼/页面/今日次数已满对话/场景01/画面.png', 'quota_dialogue', [[65,1150,830,1250]]),
        'gourd_prompt': ('抓鬼/页面/获得葫芦提示禁止操作/场景01/画面.png', 'unknown', [[350,1338,553,1405]]),
    }
    folder = ROOT / 'src/tasks/zhuagui/assets'
    provenance = {}
    for name, (identifier, page, regions) in specifications.items():
        case = cases[identifier]
        assert case['capture']['split'] == 'calibration'
        assert case['truth']['page']['status'] == 'reviewed' and case['truth']['page']['value'] == page
        frame = cv2.imdecode(np.fromfile(validate(case), dtype=np.uint8), 1)
        points = []
        for x1,y1,x2,y2 in regions:
            crop=frame[y1:y2,x1:x2]
            if name=='gourd_prompt':
                # White button glyphs are stable; animated gold particles are not.
                coordinates=np.column_stack(np.where(np.min(crop,axis=2)>235))[:,::-1]
                assert len(coordinates)>24
                chosen=[0]
                for _ in range(23):
                    distance=np.min(np.sum((coordinates[:,None]-coordinates[chosen][None,:])**2,axis=2),axis=1)
                    chosen.append(int(np.argmax(distance)))
                sampled=[(int(x),int(y),int(crop[y,x,2])*65536+int(crop[y,x,1])*256+int(crop[y,x,0])) for x,y in coordinates[chosen]]
            else:
                sampled=sampler.sample(crop)
            points.extend((x+x1,y+y1,color) for x,y,color in sampled)
        ax,ay,base = points[0]
        offsets = ','.join(f'{x-ax}|{y-ay}|0x{color:06x}' for x,y,color in points[1:])
        tap=(',tap_offset={%d,%d}'%(450-ax,1210-ay)) if name=='quota_dialogue' else ''
        region=('{%d,%d,%d,%d}'%(ax-5,ay-5,ax+5,ay+5)) if name in ('quota_dialogue','gourd_prompt') else '{35,174,868,1408}'
        feature = 'return {width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region=%s%s}\n' % (base, json.dumps(offsets),region,tap)
        (folder / (name+'.lua')).write_text(feature, encoding='utf-8')
        provenance[name] = {'case_id': identifier,  'regions': regions}
    (folder/'completed_card.json').write_text(json.dumps(provenance, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
