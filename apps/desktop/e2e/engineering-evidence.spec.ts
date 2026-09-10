import { execFileSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'

import {
  buildAppEnv,
  createSandbox,
  launchDesktop,
  waitForAppReady,
  writeEnvFile,
  writeMockProviderConfig
} from './fixtures'
import { startMockServer } from './mock-server'
import { RealSessionBuilder } from './real-session-builder'
import { expect, test } from './test'

const REPO_ROOT = path.resolve(import.meta.dirname, '../../..')
const TITLE = 'Workspace evidence acceptance'

// The fixture runs actual tests and records their actual subprocess results.
// No check outcome is mocked, and no user's profile or repository is modified.
const RUN_CHECKS = `
import subprocess, sys
from agent.verification_evidence import record_terminal_result
from agent.workspace_identity import capture_workspace
root, sid = sys.argv[1:]
for target in ('tests/test_math.py', 'tests/test_import.py'):
    before = capture_workspace(root)
    proc = subprocess.run([sys.executable, '-m', 'pytest', target, '-q'], cwd=root, capture_output=True, text=True)
    result = record_terminal_result(command='python -m pytest ' + target + ' -q', cwd=root, session_id=sid,
        exit_code=proc.returncode, output=proc.stdout + proc.stderr,
        workspace_before=before, workspace_after=capture_workspace(root))
    assert result is not None, 'test command must produce verification evidence'
`

test('actual failed and passing checks remain visible, and an external edit invalidates the evidence', async ({}, testInfo) => {
  test.setTimeout(240_000)
  const sandbox = createSandbox('engineering-evidence')
  const repo = path.join(sandbox.root, 'workspace')
  fs.mkdirSync(path.join(repo, 'tests'), { recursive: true })
  fs.writeFileSync(path.join(repo, 'pyproject.toml'), '[tool.pytest.ini_options]\n')
  fs.writeFileSync(path.join(repo, '.gitignore'), '__pycache__/\n.pytest_cache/\n')
  fs.writeFileSync(path.join(repo, 'app.py'), 'VALUE = 1\n')
  fs.writeFileSync(
    path.join(repo, 'tests/test_math.py'),
    'from app import VALUE\ndef test_value():\n    assert VALUE == 2\n'
  )
  fs.writeFileSync(
    path.join(repo, 'tests/test_import.py'),
    'from app import VALUE\ndef test_type():\n    assert isinstance(VALUE, int)\n'
  )
  execFileSync('git', ['init', '-q'], { cwd: repo, windowsHide: true })
  execFileSync('git', ['add', '.'], { cwd: repo, windowsHide: true })
  execFileSync(
    'git',
    ['-c', 'user.name=ZeusAgent E2E', '-c', 'user.email=e2e@example.invalid', 'commit', '-qm', 'fixture'],
    { cwd: repo, windowsHide: true }
  )
  const mock = await startMockServer()
  writeMockProviderConfig(sandbox.zeusHome, mock.url)
  writeEnvFile(sandbox.zeusHome)
  const builder = await RealSessionBuilder.start(sandbox.zeusHome)
  let sessionId: string
  try {
    sessionId = (await builder.createSession({ cwd: repo, title: TITLE, turns: ['Check this workspace.'] })).sessionId
  } finally {
    await builder.close()
  }
  const runChecks = () =>
    execFileSync('uv', ['run', '--active', '--no-sync', 'python', '-c', RUN_CHECKS, repo, sessionId], {
      cwd: REPO_ROOT,
      env: { ...process.env, ZEUS_HOME: sandbox.zeusHome },
      windowsHide: true,
      timeout: 60_000
    })
  runChecks()
  const { app, page } = await launchDesktop(buildAppEnv(sandbox))
  try {
    await waitForAppReady({ app, page, sandbox, cleanup: async () => undefined }, 120_000)
    await page.locator('[data-slot="sidebar"] button').filter({ hasText: TITLE }).first().click()
    await page.getByRole('button', { name: 'Evidence', exact: true }).click()
    const dialog = page.getByTestId('evidence-dialog')
    await expect(dialog.getByTestId('evidence-check')).toHaveCount(2)
    await expect(dialog.getByText(/Observed result: Failed/)).toBeVisible()
    await expect(dialog.getByText(/Observed result: Passed/)).toBeVisible()
    await dialog.getByRole('button', { name: 'Capture baseline' }).click()
    await expect(dialog.getByRole('button', { name: 'Clear baseline' })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('evidence-baseline.png') })

    fs.writeFileSync(path.join(repo, 'app.py'), 'VALUE = 2\n')
    await dialog.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(dialog.getByText('Workspace match: Needs rerun')).toHaveCount(2)
    await page.screenshot({ path: testInfo.outputPath('evidence-stale.png') })
    runChecks()
    await dialog.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(dialog.getByText(/Observed result: Passed/)).toHaveCount(2)
    await expect(dialog.getByText('Fixed', { exact: true })).toBeVisible()
    await dialog.getByRole('button', { name: 'Clear baseline' }).click()
    await expect(dialog.getByRole('button', { name: 'Clear baseline' })).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('evidence-fixed.png') })
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: 'Evidence', exact: true })).toBeFocused()
  } finally {
    await app.close().catch(() => undefined)
    await mock.close()
    sandbox.cleanup()
  }
})
