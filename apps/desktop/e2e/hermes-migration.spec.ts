import { execFileSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'

import { setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

const REPO_ROOT = path.resolve(import.meta.dirname, '../../..')
const CONTENT = 'A conversation transferred from Hermes.'
const CREATE_SOURCE = `
import sys
from pathlib import Path
from zeus_state import SessionDB
db = SessionDB(Path(sys.argv[1]) / 'state.db')
db.create_session('hermes-fixture-chat', 'cli')
db.set_session_title('hermes-fixture-chat', 'Hermes fixture')
db.append_message('hermes-fixture-chat', 'user', sys.argv[2])
db.append_message('hermes-fixture-chat', 'assistant', 'The conversation is preserved.')
db.close()
`
const INSPECT_IMPORT = `
import json, sqlite3, sys
from pathlib import Path
conn = sqlite3.connect(Path(sys.argv[1]) / 'state.db')
rows = conn.execute("SELECT s.id, m.content FROM sessions s JOIN messages m ON m.session_id=s.id WHERE s.id LIKE 'hermes:%' ORDER BY m.id").fetchall()
print(json.dumps(rows))
conn.close()
`

test('Move from Hermes previews and imports a temporary source without replacing existing data', async ({}, testInfo) => {
  test.setTimeout(180_000)
  const fixture = await setupMockBackend()
  try {
    const source = path.join(fixture.sandbox.root, 'hermes-source')
    fs.mkdirSync(path.join(source, 'memories'), { recursive: true })
    fs.writeFileSync(path.join(source, 'config.yaml'), 'temperature: 0.35\nmodel:\n  default: hermes-original-model\n')
    fs.writeFileSync(path.join(source, 'SOUL.md'), 'The imported personality.\n')
    fs.writeFileSync(path.join(source, 'memories/MEMORY.md'), 'An imported memory.\n')
    fs.writeFileSync(path.join(fixture.sandbox.zeusHome, 'SOUL.md'), 'Keep my Zeus personality.\n')
    const env = { ...process.env, ZEUS_HOME: source }
    execFileSync('uv', ['run', '--active', '--no-sync', 'python', '-c', CREATE_SOURCE, source, CONTENT], {
      cwd: REPO_ROOT, env, windowsHide: true, timeout: 30_000
    })
    const sourceBefore = fs.readFileSync(path.join(source, 'SOUL.md'), 'utf8')
    await waitForAppReady(fixture, 120_000)
    await fixture.page.keyboard.press(process.platform === 'darwin' ? 'Meta+,' : 'Control+,')
    await fixture.page.getByRole('button', { name: 'Move from Hermes', exact: true }).click()
    const panel = fixture.page.getByTestId('hermes-migration')
    await panel.getByLabel('Hermes folder').fill(source)
    await panel.getByRole('button', { name: 'Scan Hermes', exact: true }).click()
    await expect(panel.getByRole('checkbox', { name: /^Chats/ })).toBeChecked()
    await expect(panel.getByRole('checkbox', { name: /^Memories/ })).toBeChecked()
    await expect(panel.getByText(source, { exact: true })).toBeVisible()
    await fixture.page.screenshot({ path: testInfo.outputPath('hermes-preview.png') })
    expect(fs.readFileSync(path.join(fixture.sandbox.zeusHome, 'SOUL.md'), 'utf8')).toBe('Keep my Zeus personality.\n')
    await panel.getByRole('button', { name: 'Import selected', exact: true }).click()
    await expect(panel.getByText('Import complete', { exact: true })).toBeVisible({ timeout: 60_000 })
    expect(fs.readFileSync(path.join(fixture.sandbox.zeusHome, 'SOUL.md'), 'utf8')).toBe('Keep my Zeus personality.\n')
    expect(fs.readFileSync(path.join(source, 'SOUL.md'), 'utf8')).toBe(sourceBefore)
    const rows: [string, string][] = JSON.parse(execFileSync('uv', ['run', '--active', '--no-sync', 'python', '-c', INSPECT_IMPORT, fixture.sandbox.zeusHome], {
      cwd: REPO_ROOT, env: { ...process.env, ZEUS_HOME: fixture.sandbox.zeusHome }, windowsHide: true, timeout: 30_000, encoding: 'utf8'
    }))
    expect(rows.some(([id, content]) => id.startsWith('hermes:') && content === CONTENT)).toBe(true)
    await fixture.page.screenshot({ path: testInfo.outputPath('hermes-imported.png') })
  } finally {
    await fixture.cleanup()
  }
})
