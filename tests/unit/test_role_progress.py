"""Production progress storage is isolated by stable role and business date."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class RoleProgressTest(unittest.TestCase):
    def test_same_task_and_date_cannot_overwrite_another_role(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        lua.execute('''
            files={}
            io.open=function(path,mode)
                if mode=='r' and not files[path] then return nil end
                return {
                    write=function(self,text) files[path]=text;return true end,
                    close=function() return true end
                }
            end
            os.rename=function(source,target) files[target]=files[source];files[source]=nil;return true end
            loadfile=function(path) return load(files[path]) end
            first={config={business_date='20261010'},account={alias='first'},run_id='first_run'}
            second={config={business_date='20261010'},account={alias='second'},run_id='second_run'}
        ''')
        progress=lua.eval("require('progress')")[0]
        first,second=lua.globals().first,lua.globals().second
        progress.write(first,'zhuagui','done','complete',lua.table_from({'attempts':25,'completed_count':25,'reserved_energy':75,'find_retries':3}))
        self.assertIsNone(progress.read(second,'zhuagui'))
        progress.write(second,'zhuagui','running','start_requested',lua.table_from({'attempts':1,'completed_count':0,'reserved_energy':3}))
        self.assertEqual(progress.read(first,'zhuagui')['completed_count'],25)
        self.assertEqual(progress.read(first,'zhuagui')['find_retries'],3)
        self.assertIsNone(progress.read(second,'zhuagui')['find_retries'])
        self.assertEqual(progress.read(second,'zhuagui')['completed_count'],0)
        first.config.business_date='20261011'
        self.assertIsNone(progress.read(first,'zhuagui'))


if __name__=='__main__':unittest.main()
