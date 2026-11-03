"""Embed project Lua modules into one TouchSprite entry; source remains modular."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]


def build(output: Path | None = None) -> Path:
    source = ROOT / 'src'
    output = Path(output) if output is not None else ROOT / 'dist'
    output.mkdir(parents=True, exist_ok=True)
    chunks = []
    manifest = {}
    for path in sorted(source.rglob('*.lua')):
        raw = path.read_bytes()
        manifest[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
        if path == source / 'main.lua':
            continue
        module = '.'.join(path.relative_to(source).with_suffix('').parts)
        chunks.append(f'package.preload["{module}"] = function(...)\n{raw.decode("utf-8")}\nend\n')
    chunks.append((source / 'main.lua').read_text(encoding='utf-8'))
    bundle = output / 'main.lua'
    bundle.write_text('\n'.join(chunks), encoding='utf-8', newline='\n')
    manifest['bundle_sha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return bundle


if __name__ == '__main__':
    print(build())
