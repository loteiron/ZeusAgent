import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { DesktopBootstrapEvent, DesktopBootstrapState } from '@/global'

import { deferred } from '../test/deferred'

import { BOOTSTRAP_INSTALL_WAIT_TIMEOUT_MS, waitForBackendBoot } from './backend-boot-wait'

function state(overrides: Partial<DesktopBootstrapState> = {}): DesktopBootstrapState {
  return {
    active: false,
    manifest: null,
    stages: {},
    error: null,
    log: [],
    startedAt: null,
    completedAt: null,
    setupChoice: null,
    unsupportedPlatform: null,
    ...overrides
  }
}

function bridge(snapshot = Promise.resolve(state())) {
  const listeners = new Set<(event: DesktopBootstrapEvent) => void>()

  return {
    listeners,
    getBootstrapState: vi.fn(() => snapshot),
    onBootstrapEvent: vi.fn((listener: (event: DesktopBootstrapEvent) => void) => {
      listeners.add(listener)

      return () => {
        listeners.delete(listener)
      }
    }),
    emit(event: DesktopBootstrapEvent) {
      for (const listener of listeners) {listener(event)}
    }
  }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

it('retains the ordinary45s deadline for a hung backend without an install', async () => {
  const desktop = bridge()
  const result = waitForBackendBoot(new Promise<never>(() => undefined), desktop, 'backend timeout')
  const rejection = expect(result).rejects.toThrow('backend timeout')
  await vi.advanceTimersByTimeAsync(45_000)
  await rejection
  expect(desktop.listeners.size).toBe(0)
})

it('separates human choice and a long install from the final backend handshake', async () => {
  const descriptor = deferred<string>()
  const desktop = bridge(Promise.resolve(state({ setupChoice: { platform: 'win32', activeRoot: '' } })))
  const result = waitForBackendBoot(descriptor.promise, desktop, 'backend timeout')
  await vi.advanceTimersByTimeAsync(2 * BOOTSTRAP_INSTALL_WAIT_TIMEOUT_MS)
  desktop.emit({ type: 'manifest', stages: [], protocolVersion: null })
  await vi.advanceTimersByTimeAsync(257_000)
  desktop.emit({ type: 'complete', marker: {} })
  await vi.advanceTimersByTimeAsync(44_000)
  descriptor.resolve('authenticated descriptor')
  await expect(result).resolves.toBe('authenticated descriptor')
  expect(desktop.listeners.size).toBe(0)
  expect(vi.getTimerCount()).toBe(0)
})

it('anchors the install ceiling to its real start and logs cannot renew it', async () => {
  const desktop = bridge(Promise.resolve(state({ active: true, startedAt: Date.now() - 20 * 60_000 })))
  const result = waitForBackendBoot(new Promise<never>(() => undefined), desktop, 'backend timeout')
  const rejection = expect(result).rejects.toThrow('30 minutes')

  for (let minute = 0; minute < 10; minute++) {
    desktop.emit({ type: 'log', line: 'still installing' })
    desktop.emit({ type: 'stage', name: 'dependencies', state: 'running' })
    await vi.advanceTimersByTimeAsync(60_000)
  }

  await rejection
  expect(desktop.listeners.size).toBe(0)
})

it('uses the ordinary deadline after completion even when an older active snapshot arrives later', async () => {
  const snapshot = deferred<DesktopBootstrapState>()
  const desktop = bridge(snapshot.promise)
  const result = waitForBackendBoot(new Promise<never>(() => undefined), desktop, 'backend timeout')
  const rejection = expect(result).rejects.toThrow('backend timeout')
  desktop.emit({ type: 'manifest', stages: [], protocolVersion: null })
  await vi.advanceTimersByTimeAsync(257_000)
  desktop.emit({ type: 'complete', marker: {} })
  snapshot.resolve(state({ active: true, startedAt: Date.now() }))
  await vi.advanceTimersByTimeAsync(45_000)
  await rejection
})

it('cannot turn a failed install into success with late snapshot or descriptor results', async () => {
  const snapshot = deferred<DesktopBootstrapState>()
  const descriptor = deferred<string>()
  const desktop = bridge(snapshot.promise)
  const result = waitForBackendBoot(descriptor.promise, desktop, 'backend timeout')
  const rejection = expect(result).rejects.toThrow('install cancelled')
  desktop.emit({ type: 'failed', error: 'install cancelled' })
  snapshot.resolve(state({ active: true, startedAt: Date.now() }))
  descriptor.resolve('late descriptor')
  await rejection
  expect(desktop.listeners.size).toBe(0)
  expect(vi.getTimerCount()).toBe(0)
})

it('disposes its subscription on unmount cancellation and handles a late IPC rejection', async () => {
  const descriptor = deferred<string>()
  const desktop = bridge()
  const controller = new AbortController()
  const result = waitForBackendBoot(descriptor.promise, desktop, 'backend timeout', controller.signal)
  const rejection = expect(result).rejects.toThrow('window closed')
  controller.abort(new Error('window closed'))
  descriptor.reject(new Error('late IPC failure'))
  await rejection
  expect(desktop.listeners.size).toBe(0)
  expect(vi.getTimerCount()).toBe(0)
})

it('cleans up timers and an attached listener when a bridge snapshot throws synchronously', async () => {
  const desktop = bridge()
  desktop.getBootstrapState.mockImplementation(() => {
    throw new Error('snapshot bridge failed')
  })
  const pending = deferred<string>()
  await expect(waitForBackendBoot(pending.promise, desktop, 'backend timeout')).rejects.toThrow(
    'snapshot bridge failed'
  )
  expect(desktop.listeners.size).toBe(0)
  expect(vi.getTimerCount()).toBe(0)
  pending.reject(new Error('late IPC failure'))
})

it('cleans up its timer when subscription registration throws', async () => {
  const desktop = bridge()
  desktop.onBootstrapEvent.mockImplementation(() => {
    throw new Error('subscription failed')
  })
  await expect(waitForBackendBoot(new Promise<never>(() => undefined), desktop, 'backend timeout')).rejects.toThrow(
    'subscription failed'
  )
  expect(vi.getTimerCount()).toBe(0)
})
