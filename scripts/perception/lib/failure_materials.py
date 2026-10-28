"""Assemble one logged recognition round at a time; never infer annotations."""
from pathlib import Path
import math
import re


_FIND_PHASES = ('top', 'identify', 'stable', 'snapshot', 'scan', 'scroll', 'guard', 'tap', 'verify')
_FIND_COUNTS = ('required', 'features', 'candidates', 'searches', 'matches', 'selected')


def _count(value):
    if not re.fullmatch(r'\d+', value):
        raise ValueError('nonnegative integer required')
    return int(value)


def _milliseconds(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError('finite nonnegative timing required')
    return number


def _boolean(value):
    if value not in ('true', 'false'):
        raise ValueError('boolean required')
    return value == 'true'


def _profile_fields(line):
    if '[profile] ' not in line:
        return None
    fields = {}
    for token in line.split('[profile] ', 1)[1].split():
        key, separator, value = token.partition('=')
        if not separator or not value or key in fields:
            raise ValueError('invalid profile field')
        fields[key] = value
    return fields


def _profile_summary(fields):
    summary = {key: fields[key] for key in
               ('task', 'account', 'prefix', 'reason', 'solver_result', 'phase', 'timing')}
    if (not re.fullmatch(r'(shimen|zhuagui)_find_r\d+_', summary['prefix']) or
            summary['task'] != summary['prefix'].split('_')[0] or
            summary['phase'] not in _FIND_PHASES or summary['timing'] != 'at_wall_cpu_calls'):
        raise ValueError('invalid find profile identity or timing format')
    for key in ('page', 'pages'):
        summary[key] = _count(fields[key])
        if summary[key] > 7:
            raise ValueError('invalid find profile page')
    summary['captured'] = _boolean(fields['captured'])
    for key in ('wall_ms', 'other_ms'):
        summary[key] = _milliseconds(fields[key])
    return summary


def _profile_page(fields, summary):
    if fields.get('prefix') != summary['prefix'] or any(
            key in fields and fields[key] != summary[key] for key in ('task', 'account')):
        raise ValueError('profile page belongs to another question or account')
    page = {'page': _count(fields['page'])}
    if page['page'] > 7:
        raise ValueError('invalid find profile page')
    for key in _FIND_COUNTS:
        if key in fields:
            page[key] = _count(fields[key])
    for key in ('topic', 'state', 'error', 'image'):
        if key in fields:
            page[key] = fields[key]
    if 'question_matches' in fields:
        page['question_matches'] = _boolean(fields['question_matches'])
    if 'targets' in fields:
        points = [point.split(',') for point in fields['targets'].split(';')]
        if len(points) > 10 or any(len(point) != 2 for point in points):
            raise ValueError('invalid find profile targets')
        page['targets'] = [[_count(value) for value in point] for point in points]
    page['stages'] = {}
    for phase in _FIND_PHASES:
        if phase not in fields:
            continue
        values = fields[phase].split(',')
        if len(values) != 4:
            raise ValueError('invalid find profile timing')
        page['stages'][phase] = dict(zip(('at_ms', 'wall_ms', 'cpu_ms'),
                                        map(_milliseconds, values[:3])))
        page['stages'][phase]['calls'] = _count(values[3])
    return page


def _failure_profiles(archive):
    path = archive / 'log' / f'daily_{archive.name}_profile.log'
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return {}
    profiles, current = {}, None
    for line in lines:
        try:
            fields = _profile_fields(line)
            if not fields:
                continue
            if fields.get('scope') == 'find_failure':
                current = None
                summary = _profile_summary(fields)
                key = tuple(summary[name] for name in ('task', 'account', 'prefix'))
                if key in profiles:
                    profiles[key] = None  # Reused identities cannot prove one question's provenance.
                    continue
                current = dict(log=path.relative_to(archive).as_posix(), timing_unit='ms',
                               at_ms_origin='question_start', summary=summary, pages=[])
                profiles[key] = current
            elif fields.get('scope') == 'find_page' and current is not None:
                page = _profile_page(fields, current['summary'])
                if not any(row['page'] == page['page'] for row in current['pages']):
                    current['pages'].append(page)
        except (KeyError, ValueError, OverflowError):
            if re.search(r'\bscope=find_failure(?:\s|$)', line):
                current = None
    return profiles


def _link_profile(profile, images):
    linked = dict(profile, pages=[])
    by_name = {Path(image).name: image for image in images}
    for row in sorted(profile['pages'], key=lambda page: page['page']):
        page = {key: value for key, value in row.items() if key != 'image'}
        image = by_name.get(row.get('image'))
        if image and image.endswith(f"p{page['page']:02}.png"):
            page['image'] = image
        linked['pages'].append(page)
    return linked


def assemble(archive):
    archive = Path(archive)
    log = archive / 'log' / f'daily_{archive.name}.log'
    if not log.is_file():
        return []
    profiles = _failure_profiles(archive)
    results = []
    seen = set()
    for line in log.read_text(encoding='utf-8').splitlines():
        if '[recognition_materials] ' not in line:
            continue
        fields = dict(re.findall(r'(\w+)=([^\s]+)', line.split('[recognition_materials] ', 1)[1]))
        prefix = fields.get('prefix', '')
        if not re.fullmatch(r'(shimen|zhuagui)_(find|puzzle)_r\d+_', prefix) or prefix in seen:
            continue
        seen.add(prefix)
        expected_task, expected_kind = prefix.split('_')[:2]
        item = dict(task=fields.get('task'), kind=fields.get('kind'), account=fields.get('account'),
                    prefix=prefix, status='incomplete', reason='capture_not_verified', images=[])
        results.append(item)
        if (item['task'], item['kind']) != (expected_task, expected_kind):
            continue
        pages = sorted((archive / 'res').glob(f'daily_{archive.name}_*_{prefix}p[0-9][0-9].png'),
                       key=lambda path: int(re.search(r'p(\d+)\.png$', path.name)[1]))
        item['images'] = [p.relative_to(archive).as_posix() for p in pages]
        profile = profiles.get((item['task'], item['account'], prefix))
        if profile:
            item['failure_profile'] = _link_profile(profile, item['images'])
        if fields.get('from_first') != 'true' or fields.get('captured') != 'true':
            continue
        expected = fields.get('pages', '')
        if not expected.isdigit() or len(pages) != int(expected) or not pages:
            continue
        indexes = [int(re.search(r'p(\d+)\.png$', p.name)[1]) for p in pages]
        if indexes != list(range(1, len(pages) + 1)):
            item['reason'] = 'missing_or_duplicate_page'
            continue
        try:
            from PIL import Image
            for path in pages:
                with Image.open(path) as image:
                    if image.size != (900, 1600):
                        raise ValueError('full original image required')
            if item['kind'] == 'puzzle':
                if len(pages) != 1:
                    raise ValueError('one original puzzle board required')
            else:
                from scripts.perception.lib.task_review import compose_rows
                cases = {i: {'id': f'{prefix}p{i:02}', 'image': str(path)}
                         for i, path in enumerate(pages, 1)}
                strip, records, header, _ = compose_rows(cases, image_resolver=lambda case: Path(case['image']))
                item['item_height'] = strip.height
                if strip.height < 2760:
                    item['reason'] = 'insufficient_unique_rows'
                    continue
                if any(record['alignment'] and not record['alignment']['accepted'] for record in records):
                    item['reason'] = 'page_seam_not_verified'
                    continue
                stitched = Image.new('RGB', (900, 535 + strip.height), (0, 0, 0))
                stitched.paste(header.crop((0, 0, 900, 535)), (0, 0))
                stitched.paste(strip, (63, 535))
                output = archive / f'{prefix}stitched.png'
                stitched.save(output)
                item['stitched'] = output.relative_to(archive).as_posix()
            item.update(status='awaiting_visual_review', reason='check_first_last_and_seams')
        except (OSError, ValueError) as exc:
            item['reason'] = type(exc).__name__
    return results
