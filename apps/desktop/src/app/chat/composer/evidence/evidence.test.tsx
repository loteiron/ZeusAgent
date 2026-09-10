import { useStore } from '@nanostores/react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { evidenceMessages } from '@/i18n/evidence'
import { createEvidenceController, type VerificationSnapshot } from '@/store/verification'

const state = vi.hoisted(() => ({ controller: null as ReturnType<typeof createEvidenceController> | null }))
vi.mock('./use-evidence', () => ({
  useEvidence: () => ({
    ...useStore(state.controller!.state),
    refresh: state.controller!.refresh,
    baseline: state.controller!.baseline
  })
}))

import { EvidenceButton, EvidenceResults } from './index'

const sample = (): VerificationSnapshot => ({
  status: 'failed',
  session_id: 'a',
  root: '/repo',
  changed_paths: ['src/main.py'],
  checks: [
    {
      id: 1,
      command: 'python -m pytest tests/unit',
      canonical_command: 'python -m pytest tests/unit',
      kind: 'test',
      scope: 'targeted',
      status: 'failed',
      exit_code: 1,
      cwd: '/repo',
      created_at: '2026-09-10T00:00:00Z',
      output_summary: 'Expected 2, received 1',
      freshness: 'stale',
      comparison: 'regression'
    },
    {
      id: 2,
      command: 'npm run lint',
      canonical_command: 'npm run lint',
      kind: 'lint',
      scope: 'full',
      status: 'passed',
      exit_code: 0,
      cwd: '/repo',
      created_at: '2026-09-10T00:01:00Z',
      output_summary: 'Lint completed',
      freshness: 'current',
      comparison: 'fixed'
    }
  ],
  summary: { passed: 1, failed: 1, stale: 1, unknown: 0, total: 2 },
  workspace: {
    root: '/repo',
    head: 'abc',
    fingerprint: 'fp',
    status: 'ready',
    reason: '',
    changed_paths: ['src/main.py']
  },
  baseline: null
})

afterEach(() => {
  cleanup()
  state.controller?.dispose()
})

describe('workspace evidence surface', () => {
  it('shows external edits from the current workspace and removes paths once they are restored', () => {
    const data = sample()
    data.changed_paths = ['src/previous-agent-edit.py']
    data.workspace.changed_paths = ['src/external-editor.py', 'tests/new-external-test.py']

    const view = render(<EvidenceResults data={data} locale="en" messages={evidenceMessages.en} />)
    expect(screen.getByText('src/external-editor.py')).toBeTruthy()
    expect(screen.getByText('tests/new-external-test.py')).toBeTruthy()
    expect(screen.queryByText('src/previous-agent-edit.py')).toBeNull()

    view.rerender(
      <EvidenceResults
        data={{ ...data, workspace: { ...data.workspace, changed_paths: [] } }}
        locale="en"
        messages={evidenceMessages.en}
      />
    )
    expect(screen.queryByText('src/external-editor.py')).toBeNull()
    expect(screen.queryByText('tests/new-external-test.py')).toBeNull()
    expect(screen.queryByText('src/previous-agent-edit.py')).toBeNull()
  })

  it('keeps failure, stale workspace match and targeted scope visible beside an unrelated pass', () => {
    render(<EvidenceResults data={sample()} locale="en" messages={evidenceMessages.en} />)
    const rows = screen.getAllByTestId('evidence-check')
    expect(within(rows[0]).getByText(/Observed result: Failed/)).toBeTruthy()
    expect(within(rows[0]).getByText('Workspace match: Needs rerun')).toBeTruthy()
    expect(within(rows[0]).getByText('Targeted scope')).toBeTruthy()
    expect(within(rows[0]).getByText('Regression')).toBeTruthy()
    expect(within(rows[1]).getByText(/Observed result: Passed/)).toBeTruthy()
    fireEvent.click(within(rows[0]).getByText('Output'))
    expect(within(rows[0]).getByText('Expected 2, received 1')).toBeTruthy()
  })

  it('surfaces baseline capture failure and only shows saved baseline after the backend confirms it', async () => {
    let saved = false
    let reject = true
    state.controller = createEvidenceController(async method => {
      if (method === 'verification.baseline.capture') {
        if (reject) {
          throw new Error('Workspace changed during capture')
        }

        saved = true

        return { baseline: { id: 'baseline-1' } }
      }

      return {
        verification: {
          ...sample(),
          baseline: saved
            ? { id: 'baseline-1', created_at: '2026-09-10T00:02:00Z', fingerprint: 'fp', check_count: 2 }
            : null
        }
      }
    })
    await state.controller.refresh()
    render(<EvidenceButton cwd="/repo" gateway={null} sessionId="a" />)
    fireEvent.click(screen.getByRole('button', { name: 'Evidence' }))
    fireEvent.click(screen.getByRole('button', { name: 'Capture baseline' }))
    expect((await screen.findByRole('alert')).textContent).toContain('Workspace changed during capture')
    expect(screen.queryByRole('button', { name: 'Clear baseline' })).toBeNull()
    reject = false
    await act(async () => {
      await state.controller!.refresh()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Capture baseline' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Clear baseline' })).toBeTruthy())
    expect(screen.getByText(/Observed result: Failed/)).toBeTruthy()
  })
})
