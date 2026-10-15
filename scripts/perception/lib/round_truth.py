"""Score rounds from original-frame coordinates; never maintain stitched truth."""
from pathlib import Path
from scripts.perception.lib.corpus import regions


def evaluate_rounds(rounds,results):
    frames={r['id']:r for r in results};evaluated=[]
    for item in rounds:
        if item['id'].startswith('师门/'):
            members=[frames.get(identity) for identity in item['frames']]
            expected=sum(len(boxes) for locations in item['answers'].values() for boxes in locations.values())
            missed=[];selected=0
            for identity,frame in zip(item['frames'],members):
                if frame is None:missed.append(identity);continue
                taps=[a['point'] for a in frame['actions'] if a['kind']=='tap']
                boxes=[b for loc in item['answers'].values() for b in loc.get(Path(identity).name,[])]
                selected+=sum(any(x1<=x<x2 and y1<=y<y2 for x,y in taps) for x1,y1,x2,y2 in boxes)
                if frame['status']=='failed':missed.append(identity)
            evaluated.append({'id':item['id'],'topic':item['topic'],'approved_count':expected,
                'selected_count':selected,'failed_frames':missed,
                'status':'failed' if missed or selected!=expected else 'passed'})
            continue
        selected=set();wrong=[];abstained=[]
        for identity in item['frames']:
            frame=frames.get(identity)
            if frame is None:continue
            name=Path(identity).name
            visible={label:loc[name] for label,loc in item['answers'].items() if name in loc}
            taps=[a['point'] for a in frame['actions'] if a['kind']=='tap']
            if visible and not taps:abstained.append(identity)
            for x,y in taps:
                hits={label for label,boxes in visible.items() if any(x1<=x<x2 and y1<=y<y2 for x1,y1,x2,y2 in regions(boxes))}
                selected.update(hits)
                if not hits:
                    negative=any(x1<=x<x2 and y1<=y<y2 for x1,y1,x2,y2 in frame.get('known_negative_regions',[]))
                    wrong.append({'case_id':identity,'point':[x,y],'status':'wrong' if negative else 'unscored'})
        expected=[label for label,locations in item['answers'].items() if any(regions(boxes) for boxes in locations.values())]
        evaluated.append({'id':item['id'],'topic':item['topic'],'expected_answers':expected,
            'selected_answers':sorted(selected),'unselected_answers':sorted(set(expected)-selected),
            'approved_count':len(expected),'selected_count':len(selected),
            'abstained_frames_with_visible_answer':abstained,'other_taps':wrong,
            'status':'failed' if any(t['status']=='wrong' for t in wrong) else
                     'unscored' if not expected or (not selected and wrong) else 'passed' if selected else 'failed'})
    return evaluated
