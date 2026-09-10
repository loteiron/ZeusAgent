import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const { request, gateway } = vi.hoisted(() => {
  const request = vi.fn()

  return { request, gateway: { request } }
})

vi.mock('@/app/gateway/hooks/use-gateway-request', () => ({ useGatewayRequest: () => ({ gateway }) }))
vi.mock('./profile-scope', () => ({ SettingsProfileScope: () => null }))

import { HermesMigrationSettings } from './hermes-migration'

afterEach(() => {
  cleanup()
  request.mockReset()
})

describe('Move from Hermes settings', () => {
  it('requires preview and explicit category selection before importing, and surfaces an import failure', async () => {
    request.mockImplementation(async (method: string) => {
      if (method === 'hermes.migration.import') {
        throw new Error('The source changed; scan again.')
      }

      return {
        preview: {
          scan_id: 's1',
          source: '/hermes',
          target: '/zeus',
          categories: [
            { id: 'chats', label: 'Chats', count: 9, conflicts: 0 },
            { id: 'settings', label: 'Settings', count: 2, conflicts: 1 }
          ],
          warnings: []
        }
      }
    })
    render(<HermesMigrationSettings />)
    expect(request).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Import selected' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Scan Hermes' }))
    await screen.findByRole('checkbox', { name: /Chats/ })
    fireEvent.click(screen.getByRole('checkbox', { name: /Settings/ }))
    expect(request).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Import selected' }))
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        'hermes.migration.import',
        expect.objectContaining({ source: '/hermes', scan_id: 's1', categories: ['chats'] })
      )
    )
    expect((await screen.findByRole('alert')).textContent).toContain('source changed')
    expect(screen.queryByText('Import complete')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Import selected' })).toBeNull()
  })
})
