import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getActionStatus: vi.fn(),
  restartGateway: vi.fn(),
  confirm: vi.fn(),
  notify: vi.fn(),
  notifyError: vi.fn()
}))

vi.mock('@/zeus', () => api)
vi.mock('@/store/confirm', () => ({ confirm: api.confirm }))
vi.mock('@/store/notifications', () => ({ notify: api.notify, notifyError: api.notifyError }))
vi.mock('@/i18n', () => ({ translateNow: (key: string) => key }))

import { $gatewayRestarting, runGatewayRestart } from './system-actions'

describe('gateway restart outcome', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    api.getStatus.mockResolvedValue({ gateway_shared_with: ['default', 'work'] })
    api.confirm.mockResolvedValue(true)
    api.restartGateway.mockResolvedValue({ name: 'gateway-restart', pid: 100 })
  })

  afterEach(() => vi.useRealTimers())

  it('does not spawn a restart when the shared-gateway confirmation is cancelled', async () => {
    api.confirm.mockResolvedValue(false)
    expect(await runGatewayRestart()).toBe(false)
    expect(api.restartGateway).not.toHaveBeenCalled()
    expect($gatewayRestarting.get()).toBe(false)
  })

  it.each([
    { running: true, exit_code: null },
    { running: false, exit_code: null },
    { running: false, exit_code: 1 }
  ])('never announces success without a completed successful action: %j', async status => {
    api.getActionStatus.mockResolvedValue(status)
    const result = runGatewayRestart()
    await vi.runAllTimersAsync()
    expect(await result).toBe(false)
    expect(api.notify).not.toHaveBeenCalled()
    expect(api.notifyError).toHaveBeenCalledOnce()
    expect($gatewayRestarting.get()).toBe(false)
  })

  it('announces a shared restart after the child exits successfully', async () => {
    api.getActionStatus.mockResolvedValue({ running: false, exit_code: 0 })
    const result = runGatewayRestart()
    await vi.runAllTimersAsync()
    expect(await result).toBe(true)
    expect(api.notify).toHaveBeenCalledOnce()
    expect($gatewayRestarting.get()).toBe(false)
  })
})
