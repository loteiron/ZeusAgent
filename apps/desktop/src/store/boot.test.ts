import { afterEach, expect, it } from 'vitest'

import {
  $desktopBoot,
  applyDesktopBootProgress,
  completeDesktopBoot,
  failDesktopBoot,
  resumeDesktopBootForRetry
} from './boot'

afterEach(() => completeDesktopBoot())

it('keeps a terminal failure visible across multiple late main-process progress events until an explicit retry', () => {
  completeDesktopBoot()
  failDesktopBoot('Initial connection timed out')
  const failure = $desktopBoot.get()

  for (const progress of [50, 84, 94]) {
    applyDesktopBootProgress({
      error: null,
      fakeMode: false,
      message: 'Late startup progress',
      phase: 'backend.ready',
      progress,
      running: true,
      timestamp: Date.now()
    })
  }

  expect($desktopBoot.get()).toEqual(failure)
  resumeDesktopBootForRetry('Retrying startup')
  applyDesktopBootProgress({
    error: null,
    fakeMode: false,
    message: 'Connecting',
    phase: 'renderer.gateway.connect',
    progress: 95,
    running: true,
    timestamp: Date.now()
  })
  expect($desktopBoot.get().error).toBeNull()
  expect($desktopBoot.get().phase).toBe('renderer.gateway.connect')
})
