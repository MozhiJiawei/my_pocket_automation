from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class LuaSyntaxTest(unittest.TestCase):
    def test_modules_and_bundle_compile_without_execution(self):
        lua = LuaRuntime()
        paths = list((ROOT / 'src').rglob('*.lua'))
        bundle = ROOT / 'dist/main.lua'
        if bundle.exists():
            paths.append(bundle)
        self.assertGreater(len(paths), 10)
        for path in paths:
            with self.subTest(module=path.relative_to(ROOT)):
                lua.execute('return assert(load(...))', path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
