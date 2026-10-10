"""Freeze explicitly approved round annotations and project into original frames."""
from copy import deepcopy
import hashlib
import json

from scripts.perception.lib.corpus import VERIFIED, annotation


def project_region(region, capture):
    """Only fully visible objects are scored; clipped objects remain unlabelled."""
    x1, y1, x2, y2 = region
    vx1, vy1, vx2, vy2 = capture['viewport']
    origin = capture['list_origin_y']
    box = [x1+vx1, y1-origin+vy1, x2+vx1, y2-origin+vy1]
    return box if vx1 <= box[0] < box[2] <= vx2 and vy1 <= box[1] < box[3] <= vy2 else None


def approve_rounds(document, review, excluded, reviewer, evidence):
    if not reviewer or not evidence:
        raise ValueError('Human reviewer and approval evidence are required')
    document = deepcopy(document)
    cases = {c['id']: c for c in document['cases']}
    source = f'{reviewer}: {evidence}'
    frozen = []
    positive, negative = {}, {}
    for entries in review['categories'].values():
        for entry in entries:
            item = deepcopy(entry)
            for capture in item['captures']:
                if cases[capture['case_id']]['sha256'] != capture['sha256']:
                    raise ValueError('Reviewed screenshot hash does not match corpus')
            approved = []
            for candidate in item['candidate_annotations']:
                if candidate['status'] == 'uncertain':
                    continue
                candidate.update(status='user_verified', source=source)
                approved.append(candidate)
                for capture in item['captures']:
                    box = project_region(candidate['stitched_region'], capture)
                    if box:
                        positive.setdefault(capture['case_id'], []).append((box, item['id'], candidate['id']))
            # Exhaustiveness and collection completeness are independent of approval.
            item['answer_set'].update(status='user_verified', item_ids=[c['id'] for c in approved],
                                      exhaustive=False, source=source)
            item['review'] = {'reviewer': reviewer, 'evidence': evidence}
            frozen.append(item)
    by_round = {r['id']: r for r in frozen}
    for rejection in excluded:
        for capture in by_round[rejection['round_id']]['captures']:
            box = project_region(rejection['stitched_region'], capture)
            if box:
                negative.setdefault(capture['case_id'], []).append((box, rejection['label']))
    for case in document['cases']:
        if case['id'] not in positive and case['id'] not in negative and not case.get('round_annotation_source'):
            continue
        expected, truth = case['expected'], case['truth']
        # Approval establishes truth, not evidence that an algorithm passed it.
        case.setdefault('annotation_history', [])
        # Separate earlier independent evidence from regenerated round projections.
        # A later correction must remove stale positives, rather than union them forever.
        if 'independent_region_truth' not in case:
            originals = {}
            for name in ('target_regions','negative_regions'):
                prior = next((h['previous'] for h in case['annotation_history'] if h['field']==name), truth.get(name))
                if prior and prior['status'] in VERIFIED:
                    originals[name]=deepcopy(prior)
            case['independent_region_truth']=originals
        previous_source=case.get('round_annotation_source')
        case['round_annotation_source']=source
        for field, rows in [('target_regions', positive.get(case['id'], [])),
                            ('negative_regions', negative.get(case['id'], []))]:
            old = truth.get(field)
            boxes = sorted({tuple(row[0]) for row in rows})
            independent=case['independent_region_truth'].get(field)
            if independent:
                boxes = sorted(set(boxes) | {tuple(b) for b in independent['value']})
            if not boxes:
                if old and old['source'] in {source, previous_source}:
                    truth[field]=annotation(None,'pending','No approved regions in current round truth; absence is unknown')
                continue
            value = [list(box) for box in boxes]
            updated = annotation(value, 'user_verified', source)
            if old != updated:
                case['annotation_history'].append({'field': field, 'previous': old, 'approval': source})
            truth[field] = updated
            if field == 'target_regions':
                truth['target_regions_complete'] = annotation(False, 'user_verified', source)
            if field not in expected['checks']:
                expected['checks'].append(field)
        case['round_answer_refs'] = sorted({f'{round_id}/{answer_id}' for _, round_id, answer_id in positive.get(case['id'], [])})
    return document, {'schema_version': 1, 'task': 'zhuagui',
                      'review_sha256': hashlib.sha256(json.dumps(review,sort_keys=True).encode()).hexdigest(),
                      'approval': {'reviewer': reviewer, 'evidence': evidence}, 'rounds': frozen}


def evaluate_rounds(rounds, results):
    """Evaluate real planned selections, without pretending the solver enumerates all items."""
    frames = {r['id']: r for r in results}
    evaluated = []
    for round_case in rounds:
        selected, wrong, abstained = set(), [], []
        for capture in round_case['captures']:
            frame = frames.get(capture['case_id'])
            if frame is None:
                continue
            taps = [a['point'] for a in frame['actions'] if a['kind']=='tap']
            visible = {c['id']:project_region(c['stitched_region'], capture)
                       for c in round_case['candidate_annotations'] if c['status']=='user_verified'}
            visible = {key:box for key,box in visible.items() if box}
            if visible and not taps:
                abstained.append(capture['case_id'])
            for x,y in taps:
                hits = {key for key,(x1,y1,x2,y2) in visible.items() if x1<=x<x2 and y1<=y<y2}
                selected.update(hits)
                if not hits:
                    known_negative = frame.get('known_negative_regions', [])
                    rejected = any(x1<=x<x2 and y1<=y<y2 for x1,y1,x2,y2 in known_negative)
                    wrong.append({'case_id':capture['case_id'],'point':[x,y],
                                  'status':'wrong' if rejected or round_case['answer_set']['exhaustive'] else 'unscored'})
        expected = round_case['answer_set']['item_ids']
        evaluated.append({'id':round_case['id'],'topic':round_case['topic'],
                          'expected_answers':expected,'selected_answers':sorted(selected),
                          'unselected_answers':sorted(set(expected)-selected),
                          'unselected_are_not_detection_recall':True,
                          'abstained_frames_with_visible_answer':sorted(set(abstained)),
                          'other_taps':wrong,'collection_status':round_case['collection_status'],
                          'status':'failed' if any(t['status']=='wrong' for t in wrong) else 'unscored' if not expected or (not selected and wrong) else 'passed' if selected else 'failed'})
    return evaluated
