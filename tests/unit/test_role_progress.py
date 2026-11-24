"""Production runtime state is role-isolated and never accesses files."""
from pathlib import Path
import tempfile
import os
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class RoleProgressTest(unittest.TestCase):
    def test_daily_completion_survives_restart_without_task_details(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'completion.tsv'
            def runtime(alias='first',binding='abc123',verified=True,date=None):
                lua=LuaRuntime(unpack_returned_tuples=True)
                lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
                # Android rename replaces atomically; Windows C rename does not.
                lua.globals().atomic_replace=lambda source,target: (os.replace(source,target) or True)
                lua.execute('os.rename=atomic_replace')
                ctx=lua.table_from({'account':lua.table_from({'alias':alias,'identity_binding':binding}),
                    'identity_verified':verified,'config':lua.table_from({'business_date':date or lua.eval("os.date('%Y%m%d')"),
                    'completion_ledger_path':path.as_posix()})})
                return lua.eval("require('progress')")[0],ctx
            progress,ctx=runtime()
            progress.write(ctx,'shimen','running','free_find_retry_reserved')
            progress.write(ctx,'wuji','done','reward_confirmation_requested')
            self.assertFalse(path.exists())
            progress.write(ctx,'shimen','done','completion_card_verified')
            self.assertEqual(len(path.read_text().splitlines()),1)
            self.assertTrue(path.read_text().endswith('\tshimen\ttrue\n'))
            restarted,other=runtime()
            record=restarted.read(other,'shimen')
            self.assertEqual(record.status,'done')
            self.assertIsNone(record['find_retries'])
            for options in ({'alias':'second'},{'binding':'changed'},{'verified':False},{'date':'19000101'}):
                module,context=runtime(**options)
                self.assertIsNone(module.read(context,'shimen'))
            restarted.write(other,'rewards','done','daily_inventory_empty')
            restarted.write(other,'zhuagui','done','completion_card_verified')
            fresh,context=runtime()
            self.assertIsNone(fresh.read(context,'rewards'))
            self.assertEqual(fresh.read(context,'zhuagui').status,'done')
            fresh.write(context,'rewards','done','daily_inventory_empty')
            fresh.write(context,'pingdingcleared','done','reward_intentionally_unclaimed')
            final,context=runtime()
            self.assertIsNone(final.read(context,'rewards'))
            self.assertEqual(final.read(context,'pingdingcleared').stage,'reward_intentionally_unclaimed')

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
