import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'

import { renderSync } from '@zeus/ink'
import React from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { InputHandlerContext, UseComposerStateResult } from '../app/interfaces.js'
import { resetOverlayState } from '../app/overlayStore.js'
import { turnController } from '../app/turnController.js'
import { patchUiState, resetUiState } from '../app/uiStore.js'
import { useComposerState } from '../app/useComposerState.js'
import { useInputHandlers } from '../app/useInputHandlers.js'
import type { GatewayClient } from '../gatewayClient.js'

const history = vi.hoisted(() => [] as string[])
vi.mock('../lib/history.js', () => ({ load: () => history, append: (text: string) => history.push(text) }))

class Input extends EventEmitter {
  isTTY = true
  isRaw = false
  chunks: string[] = []
  readableLength = 0
  ref() {}
  unref() {}
  setEncoding() {}
  setRawMode(value: boolean) {
    this.isRaw = value
  }
  read() {
    const value = this.chunks.shift() ?? null
    this.readableLength = this.chunks.length

    return value
  }
  send(value: string) {
    this.chunks.push(value)
    this.readableLength = this.chunks.length
    this.emit('readable')
  }
}

const settle = () => new Promise(resolve => setTimeout(resolve, 30))
let instance: ReturnType<typeof renderSync> | undefined

beforeEach(() => {
  history.length = 0
  resetUiState()
  resetOverlayState()
  patchUiState({ sid: 'draft-session', busy: true })
})
afterEach(() => {
  instance?.unmount()
  instance?.cleanup()
  instance = undefined
  turnController.reset()
  resetUiState()
  resetOverlayState()
})

async function harness() {
  const stdin = new Input()
  const stdout = Object.assign(new PassThrough(), { columns: 80, rows: 24, isTTY: false })
  const stderr = Object.assign(new PassThrough(), { columns: 80, rows: 24, isTTY: false })
  const request = vi.fn(async () => ({ items: [], status: 'interrupted' }))
  const gw = { request } as unknown as GatewayClient
  const die = vi.fn()
  let composer!: UseComposerStateResult

  function Harness() {
    composer = useComposerState({ gw, submitRef: { current: vi.fn() }, sys: vi.fn() })
    useInputHandlers({
      composer,
      actions: { die, sys: vi.fn(), appendMessage: vi.fn() },
      gateway: { gw, rpc: request },
      terminal: {
        hasSelection: false,
        scrollRef: { current: null },
        scrollWithSelection: vi.fn(),
        selection: {},
        stdout
      },
      voice: { enabled: false, recording: false },
      wheelStep: 1
    } as unknown as InputHandlerContext)

    return null
  }

  instance = renderSync(React.createElement(Harness), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream
  })
  await settle()

  return {
    stdin,
    request,
    die,
    get composer() {
      return composer
    }
  }
}

it.each(['ctrl-c', 'double-escape'])('recalls a full discarded draft and detaches its image via %s', async gesture => {
  const h = await harness()
  h.composer.actions.setInputBuf(['first line'])
  h.composer.actions.setInput('tail [[ Paste 1 ]] [[ Image 1 ]]')
  h.composer.actions.setComposerTokens([
    { kind: 'paste', label: '[[ Paste 1 ]]', text: 'pasted\ncontent' },
    { kind: 'image', label: '[[ Image 1 ]]', index: 1, path: '/tmp/image.png' }
  ])
  await settle()

  if (gesture === 'ctrl-c') {
    h.stdin.send('\x03')
  } else {
    h.stdin.send('\x1b')
    await new Promise(resolve => setTimeout(resolve, 100))
    h.stdin.send('\x1b')
  }

  await new Promise(resolve => setTimeout(resolve, 100))
  expect(h.composer.state.input).toBe('')
  expect(h.composer.state.inputBuf).toEqual([])
  expect(history).toEqual(['first line\ntail pasted\ncontent'])
  expect(h.request).toHaveBeenCalledWith('image.detach', { path: '/tmp/image.png', session_id: 'draft-session' })
  expect(h.request).not.toHaveBeenCalledWith('session.interrupt', expect.anything())
  expect(h.die).not.toHaveBeenCalled()
  h.stdin.send('\x1b[A')
  await settle()
  expect(h.composer.state.input).toBe('first line\ntail pasted\ncontent')
})

it('normal submission clearing retains the attached payload for the dispatched message', async () => {
  const h = await harness()
  h.composer.actions.setComposerTokens([{ kind: 'image', label: '[[ Image 1 ]]', index: 1, path: '/tmp/image.png' }])
  await settle()
  h.composer.actions.clearIn()
  await settle()
  expect(h.composer.state.tokens).toEqual([])
  expect(h.request).not.toHaveBeenCalledWith('image.detach', expect.anything())
})

it('interrupts a busy empty composer and exits only after it is idle', async () => {
  const h = await harness()
  h.stdin.send('\x03')
  await settle()
  expect(h.request).toHaveBeenCalledWith('session.interrupt', { session_id: 'draft-session' })
  expect(h.die).not.toHaveBeenCalled()
  patchUiState({ busy: false })
  await settle()
  h.stdin.send('\x03')
  await settle()
  expect(h.die).toHaveBeenCalledOnce()
})
