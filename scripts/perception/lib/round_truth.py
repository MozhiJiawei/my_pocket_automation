"""Score rounds from original-frame coordinates; never maintain stitched truth."""
from pathlib import Path
from scripts.perception.lib.corpus import regions


def evaluate_rounds(rounds,results):
    frames={r['id']:r for r in results};evaluated=[]
    for item in rounds:
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
        expected=list(item['answers'])
        evaluated.append({'id':item['id'],'topic':item['topic'],'expected_answers':expected,
            'selected_answers':sorted(selected),'unselected_answers':sorted(set(expected)-selected),
            'abstained_frames_with_visible_answer':abstained,'other_taps':wrong,
            'status':'failed' if any(t['status']=='wrong' for t in wrong) else
                     'unscored' if not expected or (not selected and wrong) else 'passed' if selected else 'failed'})
    return evaluated
