import { afterEach, describe, expect, it, vi } from 'vitest'

import { ZeusAgentGateway } from './client'

class ResponsiveSocket extends EventTarget {
  static OPEN = 1
  readyState = 0
  static requests: { id: number; method: string }[] = []

  constructor() {
    super()
    setTimeout(() => {
      this.readyState = 1
      this.dispatchEvent(new Event('open'))
    }, 0)
  }

  send(raw: string) {
    const request = JSON.parse(raw) as { id: number; method: string }
    ResponsiveSocket.requests.push(request)

    if (request.method === 'gateway.ping') {
      this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ id: request.id, result: {} }) }))
    }
  }

  close() {
    this.readyState = 3
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('Desktop file-operation RPC deadlines', () => {
  it('keeps disk work alive beyond the ordinary deadline while enforcing each finite budget', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', ResponsiveSocket)
    ResponsiveSocket.requests = []
    const gateway = new ZeusAgentGateway()
    const connected = gateway.connect('ws://127.0.0.1:12345/api/ws')
    await vi.advanceTimersByTimeAsync(0)
    await connected

    const outcomes = new Map<string, string>()

    const methods = [
      'config.get',
      'verification.status',
      'verification.baseline.capture',
      'hermes.migration.scan',
      'hermes.migration.import'
    ]

    const calls = methods.map(method =>
      gateway.request(method).then(
        () => outcomes.set(method, 'passed'),
        error => outcomes.set(method, error.message)
      )
    )

    await vi.advanceTimersByTimeAsync(30_001)
    expect([...outcomes.keys()]).toEqual(['config.get'])
    await vi.advanceTimersByTimeAsync(60_000)
    expect(outcomes.get('verification.status')).toContain('90s')
    expect(outcomes.has('verification.baseline.capture')).toBe(false)
    await vi.advanceTimersByTimeAsync(90_000)
    expect(outcomes.get('verification.baseline.capture')).toContain('180s')
    expect(outcomes.get('hermes.migration.scan')).toContain('180s')
    expect(outcomes.has('hermes.migration.import')).toBe(false)
    await vi.advanceTimersByTimeAsync(420_000)
    expect(outcomes.get('hermes.migration.import')).toContain('600s')
    await Promise.all(calls)
    expect(ResponsiveSocket.requests.filter(request => request.method === 'hermes.migration.import')).toHaveLength(1)
    gateway.close()
  })
})
