import { describe, expect, it, vi } from 'vitest'

import { createHermesMigrationController } from './hermes-migration'

const preview = {
  scan_id: 'scan-a',
  source: '/home/hermes',
  target: '/home/zeus',
  categories: [
    { id: 'chats', label: 'Chats', count: 12, conflicts: 2 },
    { id: 'settings', label: 'Settings', count: 3, conflicts: 0 },
    { id: 'skills', label: 'Skills', count: 0, conflicts: 0 }
  ],
  warnings: ['Credentials are not transferred.']
}

describe('Hermes migration intent', () => {
  it('requires a new preview after an ambiguous import timeout and never resubmits the old operation', async () => {
    let missingSource = true

    const request = vi.fn(async (method: string) => {
      if (method === 'hermes.migration.import') {
        throw new Error('request timed out after 600s: hermes.migration.import')
      }

      if (missingSource) {
        throw new Error('Hermes folder was not found.')
      }

      return { preview }
    })

    const controller = createHermesMigrationController(request)
    await controller.scan()
    expect(controller.state.get().error).toBe('Hermes folder was not found.')
    missingSource = false
    await controller.scan()
    await controller.importSelected()
    expect(controller.state.get().error).toContain('may still be running')
    expect(controller.state.get().preview).toBeNull()
    expect(controller.state.get().result).toBeNull()
    await controller.importSelected()
    await controller.importSelected()
    expect(request).toHaveBeenCalledTimes(3)
    controller.dispose()
  })

  it('scans without importing and submits only the selected categories with the reviewed scan identity', async () => {
    const request = vi.fn(async () => ({ preview }))
    const controller = createHermesMigrationController(request)
    await controller.scan()
    expect(request).toHaveBeenCalledTimes(1)
    expect(controller.state.get().selected).toEqual(['chats', 'settings'])
    controller.select('settings', false)
    await controller.importSelected()
    expect(request).toHaveBeenLastCalledWith('hermes.migration.import', {
      source: preview.source,
      scan_id: preview.scan_id,
      categories: ['chats']
    })
    expect(controller.state.get().error).toContain('could not be confirmed')
    expect(controller.state.get().result).toBeNull()
  })

  it('invalidates old scan results after editing the source or leaving the owning profile', async () => {
    const pending: ((value: unknown) => void)[] = []
    const request = vi.fn(() => new Promise(resolve => pending.push(resolve)))
    const controller = createHermesMigrationController(request)
    const scan = controller.scan()
    controller.setSource('/different/hermes')
    pending[0]({ preview })
    await scan
    await controller.importSelected()
    expect(controller.state.get().preview).toBeNull()
    expect(request).toHaveBeenCalledTimes(1)
    const next = controller.scan()
    controller.dispose()
    pending[1]({ preview })
    await next
    expect(controller.state.get().preview).toBeNull()
  })
})
