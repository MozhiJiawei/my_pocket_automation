"""Run the real PowerShell publish guard with fake API/publisher functions."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which('pwsh') or shutil.which('powershell')


@unittest.skipUnless(SHELL, 'PowerShell is required for the publish guard simulation')
class PublishGuardTest(unittest.TestCase):
    def evaluate(self, action, state):
        source = (ROOT / 'scripts/device/ts-cli.ps1').read_text(encoding='utf-8')
        # Execute the production decision block; all external operations are replaced.
        block = source[source.index("    $state = Invoke-TouchSprite -Endpoint 'status'"):source.index('} finally {\n    if ($forwardPort')]
        script = '''
            $script:published=0; $script:endpoints=@(); $script:rejected=$false
            function Publish-Script { $script:published++ }
            function Invoke-TouchSprite {
                param($Endpoint,$Body)
                $script:endpoints += $Endpoint
                if ($Endpoint -eq 'status') { return $simulateState }
                return 'ok'
            }
            $remoteFile='fake.lua'
        ''' + f"$Action='{action}'; $simulateState='{state}'\n" + 'try { & {\n' + block + '''
            } | Out-Null } catch { $script:rejected=$true }
            @{published=$script:published; endpoints=$script:endpoints; rejected=$script:rejected} | ConvertTo-Json -Compress
        '''
        result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, check=True)
        return json.loads(result.stdout.decode('utf-8-sig'))

    def test_busy_or_unknown_blocks_both_deploy_and_run(self):
        for action in ('deploy', 'run'):
            for state in ('f01', 'f02', 'unknown'):
                with self.subTest(action=action, state=state):
                    result = self.evaluate(action, state)
                    self.assertTrue(result['rejected'])
                    self.assertEqual(result['published'], 0)
                    self.assertEqual(result['endpoints'], ['status'])

    def test_idle_deploy_does_not_start(self):
        result = self.evaluate('deploy', 'f00')
        self.assertFalse(result['rejected'])
        self.assertEqual(result['published'], 1)
        self.assertEqual(result['endpoints'], ['status'])

    def test_idle_run_publishes_and_starts_once(self):
        result = self.evaluate('run', 'f00')
        self.assertFalse(result['rejected'])
        self.assertEqual(result['published'], 1)
        self.assertEqual(result['endpoints'], ['status', 'setLuaPath', 'runLua'])

    def test_no_publishing_call_before_idle_guard(self):
        source = (ROOT / 'scripts/device/ts-cli.ps1').as_posix().replace("'", "''")
        # Check the actual AST, rather than assuming the extracted block is the only call.
        script = f"""
            $tokens=$null; $errors=$null
            $ast=[System.Management.Automation.Language.Parser]::ParseFile('{source}',[ref]$tokens,[ref]$errors)
            if ($errors.Count) {{ throw 'Invalid PowerShell source' }}
            $calls=@($ast.FindAll({{param($node) $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Publish-Script'}},$true))
            @{{count=$calls.Count; offset=$calls[0].Extent.StartOffset; guard=$ast.Extent.Text.IndexOf("if (`$state -ne 'f00')")}} | ConvertTo-Json -Compress
        """
        result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, check=True)
        data = json.loads(result.stdout.decode('utf-8-sig'))
        self.assertEqual(data['count'], 1)
        self.assertGreater(data['offset'], data['guard'])


if __name__ == '__main__':
    unittest.main()
