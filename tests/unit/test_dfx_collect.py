"""Run the real PowerShell collector against an in-memory fake ADB filesystem."""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which('pwsh') or shutil.which('powershell')
RUN = '20261014_120000'
OTHER_RUN = '20261014_130000'
DEVICE_ROOT = '/storage/emulated/0/TouchSprite/'


def main_log(prefix='daily', run=RUN):
    return f'log/{prefix}_{run}.log'


def screenshot(label='a', prefix='daily', run=RUN):
    return f'res/{prefix}_{run}_{label}.png'


def finished(prefix='daily', run=RUN, failed=False):
    if prefix == 'hello_world':
        return f'[hello_world][run={run}] script_finished\n'
    status = 'failed' if failed else 'exited_normally'
    return f'[daily][{run}][finished] script_{status}\n'


def archive_path(remote):
    kind, name = remote.split('/', 1)
    run = name.removeprefix('daily_').removeprefix('hello_world_')[:15]
    return f'{run}/{kind}/{name}'


@unittest.skipUnless(SHELL, 'PowerShell is required for the collector simulation')
class CollectGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = {}

        def case(name, files=None, **options):
            cases[name] = {'files': files or {}, **options}

        complete = {main_log(): finished(), screenshot(): 'image-a', screenshot('b'): 'image-b'}
        case('daily', {**complete, f'log/daily_{RUN}_detail.log': 'detail'})
        case('failed', {main_log(): finished(failed=True), screenshot(): 'failure-image'})
        case('hello', {main_log('hello_world'): finished('hello_world'),
                       screenshot(prefix='hello_world'): 'hello-image'})
        case('trailing_blank', {main_log(): finished() + '\n  \n\t\n', screenshot(): 'image'})
        case('running', {main_log(): finished() + '[daily] still_running\n', screenshot(): 'image'}, repetitions=2)
        case('orphan', {screenshot(): 'image', f'log/daily_{RUN}_detail.log': finished()})
        invalid = {
            'wrong_run': finished(run=OTHER_RUN),
            'wrong_prefix': finished('hello_world'),
            'leading_text': 'prefix ' + finished(),
            'leading_space': ' ' + finished(),
            'trailing_text': finished().rstrip() + ' extra\n',
            'wrong_case': finished().replace('daily', 'DAILY'),
            'generic_marker': '[finished] script_exited_normally\n',
            'empty': '\n \n',
        }
        for name, text in invalid.items():
            case(name, {main_log(): text, screenshot(): 'image'})
        for name, text in {'hello_wrong_run': finished('hello_world', OTHER_RUN),
                           'hello_daily_marker': finished(),
                           'hello_trailing_text': finished('hello_world').rstrip() + ' extra\n'}.items():
            case(name, {main_log('hello_world'): text, screenshot(prefix='hello_world'): 'image'})
        case('prefix_isolation', {**complete, main_log('hello_world'): 'running\n',
                                  screenshot(prefix='hello_world'): 'unfinished-image'})
        case('run_isolation', {**complete, main_log(run=OTHER_RUN): 'running\n',
                               screenshot(run=OTHER_RUN): 'unfinished-image'})
        case('filter', {**complete, main_log(run=OTHER_RUN): finished(run=OTHER_RUN),
                        screenshot(run=OTHER_RUN): 'other-image',
                        'log/unrelated.log': 'unrelated', 'res/account.png': 'private',
                        f'log/daily_{RUN}.png': 'wrong-directory',
                        f'res/daily_{RUN}.log': 'wrong-directory',
                        f'res/daily_{RUN}.png.lua': 'resource',
                        f'res/other_{RUN}.png': 'unrelated-prefix',
                        f'res/daily_{RUN}_label space.png': 'invalid-label',
                        f'lua/daily_{RUN}.lua': 'return true',
                        'res/tessdata/eng.traineddata': 'ocr-data'}, runId=RUN)
        for name, option in [('pull_failure', 'failPull'), ('corrupt_pull', 'corruptPull'),
                             ('source_changed_on_pull', 'changeOnPull'), ('invalid_hash', 'invalidHash')]:
            case(name, complete, existing={archive_path(screenshot()): 'previous-verified-archive'},
                 **{option: screenshot()})
        case('delete_failure', complete, failDelete=screenshot())
        case('remote_main_changed', complete, mutateRemoteAfterDelete={main_log(): finished() + 'new-write\n'})
        case('remote_sibling_changed', complete, mutateRemoteAfterDelete={screenshot('b'): 'changed-image'})
        case('local_sibling_changed', complete,
             mutateLocalAfterDelete={archive_path(screenshot('b')): 'changed-archive'})
        case('new_artifact_on_pull', complete, addOnPull={screenshot('late'): 'late-image'})
        case('no_matching_run', complete, runId=OTHER_RUN)
        case('watch_append', {main_log(): f'[daily][{RUN}] running\n', screenshot(): 'image'},
             watch=True, repetitions=2, changeOnPull=main_log(),
             changeOnPullContent=f'[daily][{RUN}] running\n' + finished(),
             existing={archive_path(main_log()): 'previous-verified-archive'})
        case('watch_corrupt_pull', complete, watch=True, corruptPull=screenshot(),
             existing={archive_path(screenshot()): 'previous-verified-archive'})
        unfinished = {**complete, main_log(): f'[daily][{RUN}] running\n'}
        orphan = {screenshot(): 'image-a', screenshot('b'): 'image-b'}
        case('idle_unfinished', unfinished, statuses=['f00'])
        case('idle_orphan', orphan, statuses=['f00'])
        case('idle_becomes_busy', unfinished, statuses=['f00', 'f00', 'f01'])
        case('idle_orphan_becomes_busy', orphan, statuses=['f00', 'f00', 'f01'])
        case('idle_unavailable', unfinished, statuses=['unavailable'])
        case('idle_orphan_unavailable', orphan, statuses=['unavailable'])
        case('idle_recheck_unavailable', unfinished, statuses=['f00', 'f00', 'unavailable'])
        cls.cases = cases

        source = (ROOT / 'scripts/device/collect-debug.ps1').as_posix().replace("'", "''")
        encoded = base64.b64encode(json.dumps(cases).encode()).decode()
        script = r'''
            $ErrorActionPreference = 'Stop'
            $WarningPreference = 'SilentlyContinue'
            [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
            $tokens=$null; $parseErrors=$null
            $ast=[System.Management.Automation.Language.Parser]::ParseFile('__SOURCE__',[ref]$tokens,[ref]$parseErrors)
            if ($parseErrors.Count) { throw 'Invalid collector PowerShell source' }
            $definitions=@($ast.FindAll({param($node)
                $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
            },$true))
            foreach ($name in @('Invoke-Adb','Get-DeviceHash','Test-DeviceIdle','Collect-Runs')) {
                if ($name -notin $definitions.Name) { throw "Missing production function: $name" }
            }
            foreach ($definition in $definitions) {
                Invoke-Expression $definition.Extent.Text
            }
            function Get-FakeHash {
                param([byte[]]$Bytes)
                $sha=[Security.Cryptography.SHA256]::Create()
                try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
                finally { $sha.Dispose() }
            }
            function Get-ArchiveSnapshot {
                $snapshot=@{}
                if (Test-Path -LiteralPath $archiveRoot) {
                    foreach ($file in @(Get-ChildItem -LiteralPath $archiveRoot -Recurse -File)) {
                        $relative=$file.FullName.Substring($archiveRoot.Length+1).Replace('\','/')
                        $snapshot[$relative]=[Convert]::ToBase64String([IO.File]::ReadAllBytes($file.FullName))
                    }
                }
                return $snapshot
            }
            function Test-DeviceIdle {
                $state='f01'
                if ($scenario.statuses) {
                    $index=[Math]::Min($script:statusCalls,$scenario.statuses.Count-1)
                    $state=$scenario.statuses[$index]
                }
                $script:statusCalls++
                $script:calls+=@{op='status'; state=$state}
                return ($state -eq 'f00')
            }
            function Invoke-Adb {
                param([string[]]$Arguments)
                if ($Arguments.Count -lt 4 -or $Arguments[0] -ne '-s' -or $Arguments[1] -ne 'fake-device') {
                    throw "Unexpected ADB target: $Arguments"
                }
                if ($Arguments[2] -eq 'shell' -and $Arguments[3] -eq 'ls' -and $Arguments[4] -eq '-1' -and $Arguments.Count -eq 6) {
                    $directory=$Arguments[5]+'/'
                    $script:calls+=@{op='ls'; path=$Arguments[5]}
                    return @($script:remote.Keys | Where-Object { $_.StartsWith($directory) } |
                        ForEach-Object { $_.Substring($directory.Length).Split('/')[0] } | Sort-Object -Unique)
                }
                if ($Arguments[2] -eq 'shell' -and $Arguments[3] -eq 'sha256sum' -and $Arguments.Count -eq 5) {
                    $path=$Arguments[4]
                    $script:calls+=@{op='hash'; path=$path}
                    if (-not $script:remote.ContainsKey($path)) { throw "Missing fake file: $path" }
                    if ($scenario.invalidHash -and $path -eq "$deviceRoot/$($scenario.invalidHash)") { return 'invalid hash' }
                    return "$(Get-FakeHash $script:remote[$path])  $path"
                }
                if ($Arguments[2] -eq 'pull' -and $Arguments.Count -eq 5) {
                    $path=$Arguments[3]; $destination=$Arguments[4]
                    $script:calls+=@{op='pull'; path=$path; local=$destination}
                    if (-not $script:remote.ContainsKey($path)) { throw "Missing fake file: $path" }
                    $bytes=[byte[]]$script:remote[$path]
                    if ($scenario.corruptPull -and $path -eq "$deviceRoot/$($scenario.corruptPull)") {
                        $bytes=[Text.Encoding]::UTF8.GetBytes('corrupted transfer')
                    }
                    [IO.File]::WriteAllBytes($destination,$bytes)
                    if ($scenario.failPull -and $path -eq "$deviceRoot/$($scenario.failPull)") { throw 'Injected pull failure' }
                    if ($scenario.changeOnPull -and $path -eq "$deviceRoot/$($scenario.changeOnPull)") {
                        $changedContent='new source bytes'
                        if ($scenario.changeOnPullContent) { $changedContent=$scenario.changeOnPullContent }
                        $script:remote[$path]=[Text.Encoding]::UTF8.GetBytes($changedContent)
                    }
                    foreach ($property in $scenario.addOnPull.PSObject.Properties) {
                        $script:remote["$deviceRoot/$($property.Name)"]=[Text.Encoding]::UTF8.GetBytes($property.Value)
                    }
                    return 'copied'
                }
                if ($Arguments[2] -eq 'shell' -and $Arguments[3] -eq 'rm' -and $Arguments[4] -eq '--' -and $Arguments.Count -eq 6) {
                    $path=$Arguments[5]
                    $script:calls+=@{op='rm'; path=$path; archive=(Get-ArchiveSnapshot)}
                    if ($scenario.failDelete -and $path -eq "$deviceRoot/$($scenario.failDelete)") { throw 'Injected delete failure' }
                    $script:remote.Remove($path)
                    $script:deleted+=@($path)
                    if ($script:deleted.Count -eq 1) {
                        foreach ($property in $scenario.mutateRemoteAfterDelete.PSObject.Properties) {
                            $script:remote["$deviceRoot/$($property.Name)"]=[Text.Encoding]::UTF8.GetBytes($property.Value)
                        }
                        foreach ($property in $scenario.mutateLocalAfterDelete.PSObject.Properties) {
                            [IO.File]::WriteAllBytes((Join-Path $archiveRoot $property.Name),[Text.Encoding]::UTF8.GetBytes($property.Value))
                        }
                    }
                    return
                }
                throw "Unexpected ADB operation: $Arguments"
            }
            $casesJson=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__CASES__'))
            $cases=ConvertFrom-Json $casesJson
            $results=@{}
            $Device='fake-device'; $deviceRoot='/storage/emulated/0/TouchSprite'
            foreach ($property in $cases.PSObject.Properties) {
                $scenario=$property.Value
                $archiveRoot=Join-Path '__TEMP__' $property.Name
                New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null
                $RunId=$scenario.runId
                $Watch=[bool]$scenario.watch
                $script:remote=@{}; $script:calls=@(); $script:deleted=@()
                $script:statusCalls=0
                foreach ($file in $scenario.files.PSObject.Properties) {
                    $script:remote["$deviceRoot/$($file.Name)"]=[Text.Encoding]::UTF8.GetBytes($file.Value)
                }
                foreach ($file in $scenario.existing.PSObject.Properties) {
                    $path=Join-Path $archiveRoot $file.Name
                    New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
                    [IO.File]::WriteAllBytes($path,[Text.Encoding]::UTF8.GetBytes($file.Value))
                }
                $errorMessage=$null
                $iterations=@()
                $repetitions=1
                if ($scenario.repetitions) { $repetitions=$scenario.repetitions }
                try {
                    for ($i=0;$i -lt $repetitions;$i++) {
                        Collect-Runs | Out-Null
                        $iterations+=@{archive=(Get-ArchiveSnapshot); deleted=@($script:deleted);
                            remaining=@($script:remote.Keys)}
                    }
                }
                catch { $errorMessage=$_.Exception.Message }
                $remaining=@{}
                foreach ($path in $script:remote.Keys) {
                    $remaining[$path.Substring($deviceRoot.Length+1)]=[Convert]::ToBase64String($script:remote[$path])
                }
                $results[$property.Name]=@{error=$errorMessage; calls=@($script:calls);
                    deleted=@($script:deleted); remaining=$remaining; archive=(Get-ArchiveSnapshot);
                    iterations=@($iterations)}
            }
            '[DFX_RESULTS]'+($results | ConvertTo-Json -Compress -Depth 10)
        '''
        with tempfile.TemporaryDirectory(prefix='dfx-collect-') as temp:
            script = script.replace('__SOURCE__', source).replace('__CASES__', encoded)
            script = script.replace('__TEMP__', Path(temp).as_posix().replace("'", "''"))
            path = Path(temp) / 'simulate.ps1'
            path.write_text(script, encoding='utf-8-sig')
            result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-File', str(path)],
                                    capture_output=True, check=True, timeout=35)
            output = result.stdout.decode('utf-8-sig')
            payload = next(line.removeprefix('[DFX_RESULTS]') for line in output.splitlines()
                           if line.startswith('[DFX_RESULTS]'))
            cls.results = json.loads(payload)

    def calls(self, name, operation):
        return [call for call in self.results[name]['calls'] if call['op'] == operation]

    def test_completed_groups_archive_every_file_before_deleting_main_log_last(self):
        for name, prefix in [('daily', 'daily'), ('failed', 'daily'), ('hello', 'hello_world'), ('trailing_blank', 'daily')]:
            with self.subTest(name=name):
                result = self.results[name]
                self.assertIsNone(result['error'])
                self.assertEqual(result['remaining'], {})
                self.assertEqual(result['deleted'][-1], DEVICE_ROOT + main_log(prefix))
                expected = {archive_path(path): base64.b64encode(content.encode()).decode()
                            for path, content in self.cases[name]['files'].items()}
                self.assertEqual(result['archive'], expected)
                self.assertEqual(self.calls(name, 'status'), [])
                for call in self.calls(name, 'rm'):
                    self.assertEqual(call['archive'], expected)
                since_delete = []
                for call in result['calls']:
                    if call['op'] == 'hash':
                        since_delete.append(call['path'])
                    if call['op'] == 'rm':
                        self.assertIn(DEVICE_ROOT + main_log(prefix), since_delete)
                        self.assertIn(call['path'], since_delete)
                        since_delete = []
                hashes = [call['path'] for call in self.calls(name, 'hash')]
                for path in result['deleted']:
                    self.assertGreaterEqual(hashes.count(path), 3)

    def test_pull_targets_are_unique_pending_files_in_the_archive_directory(self):
        result = self.results['running']
        pulls = self.calls('running', 'pull')
        self.assertEqual(len(pulls), 4)
        pending = [Path(call['local']) for call in pulls]
        self.assertEqual(len(set(pending)), len(pending))
        for path, call in zip(pending, pulls):
            self.assertTrue(path.name.endswith('.pending'))
            remote = call['path'].removeprefix(DEVICE_ROOT)
            self.assertTrue(path.parent.as_posix().endswith('/' + str(Path(archive_path(remote)).parent).replace('\\', '/')))
        self.assertFalse(any(path.endswith('.pending') for path in result['archive']))

    def test_running_or_orphan_groups_are_collected_without_deleting_sources(self):
        for name in ('running', 'orphan'):
            with self.subTest(name=name):
                result = self.results[name]
                self.assertIsNone(result['error'])
                self.assertEqual(result['deleted'], [])
                self.assertEqual(set(result['remaining']), set(self.cases[name]['files']))
                self.assertEqual(set(result['archive']), {archive_path(path) for path in self.cases[name]['files']})

    def test_completion_marker_must_be_the_exact_last_nonblank_line_for_its_group(self):
        for name in ('wrong_run', 'wrong_prefix', 'leading_text', 'leading_space', 'trailing_text',
                     'wrong_case', 'generic_marker', 'empty', 'hello_wrong_run', 'hello_daily_marker', 'hello_trailing_text'):
            with self.subTest(name=name):
                result = self.results[name]
                self.assertIsNone(result['error'])
                self.assertEqual(result['deleted'], [])
                self.assertEqual(set(result['remaining']), set(self.cases[name]['files']))

    def test_prefixes_and_run_ids_cannot_supply_each_others_completion_evidence(self):
        for name in ('prefix_isolation', 'run_isolation'):
            with self.subTest(name=name):
                result = self.results[name]
                self.assertIsNone(result['error'])
                self.assertEqual(set(result['deleted']), {DEVICE_ROOT + main_log(), DEVICE_ROOT + screenshot(), DEVICE_ROOT + screenshot('b')})
                expected = {path for path in self.cases[name]['files'] if DEVICE_ROOT + path not in result['deleted']}
                self.assertEqual(set(result['remaining']), expected)

    def test_run_filter_and_filename_whitelist_leave_other_files_untouched(self):
        result = self.results['filter']
        selected = {main_log(), screenshot(), screenshot('b')}
        self.assertIsNone(result['error'])
        self.assertEqual(set(result['archive']), {archive_path(path) for path in selected})
        self.assertEqual(set(result['remaining']), set(self.cases['filter']['files']) - selected)
        accessed = {call['path'].removeprefix(DEVICE_ROOT) for call in result['calls'] if call['op'] != 'ls'}
        self.assertEqual(accessed, selected)

    def test_failed_or_unverified_copy_preserves_existing_archive_and_entire_source_group(self):
        for name in ('pull_failure', 'corrupt_pull', 'source_changed_on_pull', 'invalid_hash', 'watch_corrupt_pull'):
            with self.subTest(name=name):
                result = self.results[name]
                self.assertIsNotNone(result['error'])
                self.assertEqual(result['deleted'], [])
                self.assertEqual(set(result['remaining']), set(self.cases[name]['files']))
                self.assertEqual(base64.b64decode(result['archive'][archive_path(screenshot())]).decode(),
                                 'previous-verified-archive')
                self.assertFalse(any(path.endswith('.pending') for path in result['archive']))

    def test_delete_failure_keeps_main_log_and_remaining_sources(self):
        result = self.results['delete_failure']
        self.assertIsNotNone(result['error'])
        self.assertEqual(result['deleted'], [])
        self.assertEqual(set(result['remaining']), set(self.cases['delete_failure']['files']))
        self.assertNotIn(DEVICE_ROOT + main_log(), [call['path'] for call in self.calls('delete_failure', 'rm')])

    def test_cleanup_rechecks_main_source_and_each_remaining_source_or_archive(self):
        for name in ('remote_main_changed', 'remote_sibling_changed', 'local_sibling_changed'):
            with self.subTest(name=name):
                result = self.results[name]
                self.assertEqual(result['deleted'], [DEVICE_ROOT + screenshot()])
                self.assertEqual([call['path'] for call in self.calls(name, 'rm')], result['deleted'])
                self.assertIn(main_log(), result['remaining'])
                self.assertIn(screenshot('b'), result['remaining'])

    def test_new_artifact_during_collection_keeps_the_main_log_and_whole_source_group(self):
        result = self.results['new_artifact_on_pull']
        self.assertIsNone(result['error'])
        self.assertEqual(result['deleted'], [])
        self.assertEqual(set(result['remaining']), set(self.cases['new_artifact_on_pull']['files']) | {screenshot('late')})
        self.assertNotIn(archive_path(screenshot('late')), result['archive'])

    def test_no_matching_run_does_not_touch_any_source_or_existing_archive(self):
        result = self.results['no_matching_run']
        self.assertIsNotNone(result['error'])
        self.assertEqual(result['deleted'], [])
        self.assertEqual(result['archive'], {})
        self.assertEqual(set(result['remaining']), set(self.cases['no_matching_run']['files']))
        self.assertEqual([call for call in result['calls'] if call['op'] != 'ls'], [])

    def test_watch_retries_an_appending_log_without_replacing_archive_or_deleting_source(self):
        result = self.results['watch_append']
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['iterations']), 2)
        first, second = result['iterations']
        self.assertEqual(first['deleted'], [])
        self.assertEqual(set(first['remaining']), {DEVICE_ROOT + path for path in self.cases['watch_append']['files']})
        self.assertEqual(first['archive'], {archive_path(main_log()):
                         base64.b64encode(b'previous-verified-archive').decode()})
        self.assertEqual(second['remaining'], [])
        self.assertEqual(result['remaining'], {})
        self.assertEqual(result['deleted'], [DEVICE_ROOT + screenshot(), DEVICE_ROOT + main_log()])
        self.assertEqual(base64.b64decode(result['archive'][archive_path(main_log())]).decode(),
                         self.cases['watch_append']['changeOnPullContent'])
        self.assertFalse(any(path.endswith('.pending') for path in result['archive']))

    def test_verified_idle_device_allows_archived_orphan_and_unfinished_groups_to_be_cleaned(self):
        for name in ('idle_orphan', 'idle_unfinished'):
            with self.subTest(name=name):
                result = self.results[name]
                self.assertIsNone(result['error'])
                self.assertEqual(result['remaining'], {})
                expected = {archive_path(path): base64.b64encode(content.encode()).decode()
                            for path, content in self.cases[name]['files'].items()}
                self.assertEqual(result['archive'], expected)
                self.assertEqual(len(self.calls(name, 'status')), len(expected) + 1)
                for call in self.calls(name, 'rm'):
                    self.assertEqual(call['archive'], expected)
                if name == 'idle_unfinished':
                    self.assertEqual(result['deleted'][-1], DEVICE_ROOT + main_log())

    def test_idle_cleanup_stops_before_next_delete_when_device_becomes_busy_or_unavailable(self):
        for name in ('idle_becomes_busy', 'idle_orphan_becomes_busy', 'idle_recheck_unavailable'):
            with self.subTest(name=name):
                result = self.results[name]
                self.assertIsNone(result['error'])
                self.assertEqual(result['deleted'], [DEVICE_ROOT + screenshot()])
                self.assertEqual(len(self.calls(name, 'rm')), 1)
                self.assertEqual(len(self.calls(name, 'status')), 3)
                self.assertEqual(set(result['remaining']), set(self.cases[name]['files']) - {screenshot()})
                self.assertEqual(set(result['archive']), {archive_path(path) for path in self.cases[name]['files']})

    def test_unavailable_device_status_preserves_all_orphan_and_unfinished_sources(self):
        for name in ('idle_unavailable', 'idle_orphan_unavailable'):
            with self.subTest(name=name):
                result = self.results[name]
                self.assertIsNone(result['error'])
                self.assertEqual(result['deleted'], [])
                self.assertEqual(set(result['remaining']), set(self.cases[name]['files']))
                self.assertEqual(set(result['archive']), {archive_path(path) for path in self.cases[name]['files']})
                self.assertEqual([call['state'] for call in self.calls(name, 'status')], ['unavailable'])


if __name__ == '__main__':
    unittest.main()
