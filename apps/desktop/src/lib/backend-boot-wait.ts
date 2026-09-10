import type { DesktopBootstrapEvent, DesktopBootstrapState } from '@/global'

import { BACKEND_BOOT_WAIT_TIMEOUT_MS, TimeoutError } from './with-timeout'

// First-run extraction, managed Python and dependency installation are not a
// backend spawn. Bound the whole install attempt to 30 minutes; log/stage
// updates must never renew this ceiling. Human setup-choice time is separate.
export const BOOTSTRAP_INSTALL_WAIT_TIMEOUT_MS = 30 * 60_000

type BootstrapBridge = Partial<Pick<NonNullable<Window['zeusDesktop']>, 'getBootstrapState' | 'onBootstrapEvent'>>
type WaitPhase = 'backend' | 'choice' | 'install'

/** Wait for a boot descriptor/publication using Electron's install lifecycle. */
export function waitForBackendBoot<T>(
  pending: Promise<T>,
  desktop: BootstrapBridge | undefined,
  message: string,
  signal?: AbortSignal
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false
    let phase: WaitPhase = 'backend'
    let installDeadline: number | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    let off: (() => void) | undefined
    let revision = 0

    const cleanup = () => {
      clearTimeout(timer)
      off?.()
      signal?.removeEventListener('abort', aborted)
    }

    const fail = (error: unknown) => {
      if (settled) {return}
      settled = true
      cleanup()
      reject(error)
    }

    const aborted = () => fail(signal?.reason ?? new Error('Desktop boot was cancelled'))

    const arm = (duration: number, reason: string) => {
      clearTimeout(timer)
      timer = setTimeout(() => fail(new TimeoutError(reason)), Math.max(0, duration))
    }

    const transition = (next: WaitPhase, startedAt?: number | null) => {
      if (settled) {return}

      if (next === 'install') {
        const start =
          typeof startedAt === 'number' && Number.isFinite(startedAt) ? Math.min(Date.now(), startedAt) : Date.now()

        installDeadline = Math.min(installDeadline ?? Infinity, start + BOOTSTRAP_INSTALL_WAIT_TIMEOUT_MS)
        phase = next
        arm(installDeadline - Date.now(), 'Timed out installing the ZeusAgent runtime after 30 minutes')
      } else if (next !== phase) {
        phase = next
        clearTimeout(timer)

        if (next === 'backend') {arm(BACKEND_BOOT_WAIT_TIMEOUT_MS, message)}
      }
    }

    const snapshot = (state: DesktopBootstrapState) => {
      if (state.error) {fail(new Error(state.error))}
      else if (state.setupChoice) {transition('choice')}
      else {transition(state.active ? 'install' : 'backend', state.startedAt)}
    }

    const event = (value: DesktopBootstrapEvent) => {
      // Cosmetic events cannot renew deadlines or supersede the initial state
      // snapshot. Lifecycle events are newer authority than an in-flight read.
      if (value.type === 'log' || value.type === 'stage') {return}
      revision += 1

      if (value.type === 'failed') {fail(new Error(value.error))}
      else if (value.type === 'manifest') {transition('install')}
      else if (value.type === 'setup-choice') {transition(value.active ? 'choice' : 'backend')}
      else if (value.type === 'complete' || value.type === 'dismissed') {transition('backend')}
    }

    arm(BACKEND_BOOT_WAIT_TIMEOUT_MS, message)
    // Attach both handlers even when already cancelled so late IPC rejection
    // remains handled and cannot revive this disposed boot attempt.
    pending.then(value => {
      if (settled) {return}
      settled = true
      cleanup()
      resolve(value)
    }, fail)
    signal?.addEventListener('abort', aborted, { once: true })

    if (signal?.aborted) {aborted()}

    if (settled) {return}

    try {
      off = desktop?.onBootstrapEvent?.(event)

      if (settled) {
        off?.()

        return
      }

      const snapshotRevision = revision
      void desktop
        ?.getBootstrapState?.()
        .then(state => {
          if (!settled && revision === snapshotRevision) {snapshot(state)}
        })
        .catch(() => undefined) // Older bridges retain the ordinary finite budget.
    } catch (error) {
      fail(error)
    }
  })
}
