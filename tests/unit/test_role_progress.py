"""Production runtime state is role-isolated and never accesses files."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class RoleProgressTest(unittest.TestCase):
    def test_runtime_state_is_role_isolated_and_never_touches_files(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        lua.execute("io.open=function() error('no state file IO') end;loadfile=function() error('no saved state') end;os.rename=function() error('no state file rename') end")
        progress=lua.eval("require('progress')")[0]
        first=lua.table_from({'account':lua.table_from({'alias':'first'})})
        second=lua.table_from({'account':lua.table_from({'alias':'second'})})
        progress.write(first,'zhuagui','running','retry',lua.table_from({'find_retries':3}))
        self.assertIsNone(progress.read(second,'zhuagui'))
        progress.write(second,'zhuagui','done','completion_card_verified')
        self.assertEqual(progress.read(first,'zhuagui')['find_retries'],3)
        first.account.alias='second'
        self.assertIsNone(progress.read(first,'zhuagui'))
        first.account.alias='first'
        self.assertEqual(progress.read(first,'zhuagui')['find_retries'],3)
        restarted=lua.table_from({'account':lua.table_from({'alias':'first'})})
        self.assertIsNone(progress.read(restarted,'zhuagui'))
        self.assertIsNone(progress.read(first,'shimen'))


if __name__=='__main__':unittest.main()
