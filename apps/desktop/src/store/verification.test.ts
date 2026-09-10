import { describe, expect, it, vi } from 'vitest'

import { createEvidenceController, parseVerification } from './verification'

const snapshot = (status = 'failed') => ({
  status,
  session_id: 'stored-a',
  root: '/repo',
  evidence: null,
  changed_paths: [],
  checks: [
    {
      id: 1,
      command: 'npm test',
      canonical_command: 'npm test',
      kind: 'test',
      scope: 'full',
      status: 'failed',
      exit_code: 1,
      cwd: '/repo',
      created_at: '2026-09-10T01:00:00Z',
      output_summary: 'assertion failed',
      freshness: 'current',
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
      created_at: '2026-09-10T01:01:00Z',
      output_summary: '',
      freshness: 'current',
      comparison: 'fixed'
    }
  ],
  summary: { passed: 1, failed: 1, stale: 0, unknown: 0, total: 2 },
  workspace: { root: '/repo', fingerprint: 'fp', head: 'abc', status: 'ready', reason: '', changed_paths: [] },
  baseline: null
})

describe('workspace evidence requests', () => {
  it('keeps the failed check beside a later passing check, and honors backend freshness', () => {
    const data = snapshot()
    data.checks[0].freshness = 'stale'
    const parsed = parseVerification(data)
    expect(parsed?.status).toBe('failed')
    expect(parsed?.checks.map(check => [check.status, check.freshness])).toEqual([
      ['failed', 'stale'],
      ['passed', 'current']
    ])
  })

  it('coalesces an event burst behind a slow read and never publishes a disposed session request', async () => {
    const pending: ((value: unknown) => void)[] = []
    const request = vi.fn(() => new Promise<unknown>(resolve => pending.push(resolve)))
    const controller = createEvidenceController(request)
    const older = controller.refresh()
    const bursts = Array.from({ length: 20 }, () => controller.refresh())
    expect(request).toHaveBeenCalledTimes(1)
    pending[0]({ verification: snapshot('failed') })
    await Promise.resolve()
    expect(controller.state.get().data?.status).toBe('failed')
    expect(request).toHaveBeenCalledTimes(2)
    pending[1]({ verification: snapshot('needs_rerun') })
    await older
    await Promise.all(bursts)
    expect(controller.state.get().data?.status).toBe('needs_rerun')
    const disposed = controller.refresh()
    controller.dispose()
    pending[2]({ verification: snapshot('passed') })
    await disposed
    expect(controller.state.get().data?.status).toBe('needs_rerun')
  })

  it('does not pretend baseline capture succeeded and reloads authoritative state after success', async () => {
    let rejectCapture = true

    const request = vi.fn(async (method: string) => {
      if (method === 'verification.baseline.capture') {
        if (rejectCapture) {
          throw new Error('Workspace changed during capture')
        }

        return { baseline: { id: 'b1' } }
      }

      const data = snapshot()

      return {
        verification: {
          ...data,
          baseline: rejectCapture
            ? null
            : { id: 'b1', created_at: '2026-09-10T01:02:00Z', fingerprint: 'fp', check_count: 2 }
        }
      }
    })

    const controller = createEvidenceController(request)
    await controller.refresh()
    await controller.baseline('capture')
    expect(controller.state.get().error).toContain('Workspace changed')
    expect(controller.state.get().data?.baseline).toBeNull()
    rejectCapture = false
    await controller.baseline('capture')
    expect(controller.state.get().data?.baseline?.id).toBe('b1')
    expect(controller.state.get().data?.status).toBe('failed')
  })

  it('rejects evidence belonging to another session', async () => {
    const controller = createEvidenceController(async () => ({ verification: snapshot() }), ['stored-b'])
    await controller.refresh()
    expect(controller.state.get().data).toBeNull()
    expect(controller.state.get().error).toContain('another session')
  })

  it('treats an already-cleared baseline as an idempotent success and reloads the report', async () => {
    const request = vi.fn(async (method: string) => method === 'verification.baseline.clear' ? { cleared: false } : { verification: snapshot() })
    const controller = createEvidenceController(request)
    await controller.baseline('clear')
    expect(controller.state.get().error).toBeNull()
    expect(controller.state.get().data?.baseline).toBeNull()
    expect(request).toHaveBeenLastCalledWith('verification.status')
  })
})
