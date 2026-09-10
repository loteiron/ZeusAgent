import { useStore } from '@nanostores/react'
import { useEffect, useMemo } from 'react'

import { ambientRequestFor, isSessionGone } from '@/store/session-gone-latch'
import { requestForOwnedSession, storedSessionIdForRuntimeId } from '@/store/session-states'
import { createEvidenceController } from '@/store/verification'
import { $workspaceChangeTick } from '@/store/workspace-events'
import type { ZeusAgentGateway } from '@/zeus'

export function useEvidence(sessionId: string, cwd: string, gateway: ZeusAgentGateway | null) {
  const storedId = storedSessionIdForRuntimeId(sessionId) ?? sessionId

  const controller = useMemo(
    () =>
      createEvidenceController(
        async method => {
          if (!gateway) {
            throw new Error('Connect to the agent to read workspace evidence.')
          }

          return requestForOwnedSession(sessionId, ambientRequestFor(gateway), method, { session_id: sessionId, cwd })
        },
        [sessionId, storedId]
      ),
    [sessionId, storedId, cwd, gateway]
  )

  const state = useStore(controller.state)

  useEffect(() => {
    controller.activate()
    let timer: ReturnType<typeof setTimeout> | undefined

    const refresh = () => {
      if (document.visibilityState !== 'hidden' && !isSessionGone(sessionId) && !controller.state.get().loading) {
        void controller.refresh()
      }
    }

    const schedule = () => {
      if (timer) {
        clearTimeout(timer)
      }

      timer = setTimeout(() => {
        if (document.visibilityState !== 'hidden' && !isSessionGone(sessionId)) {void controller.refresh()}
      }, 600)
    }

    refresh()
    const offWorkspace = $workspaceChangeTick.listen(schedule)

    const offEvents = gateway?.onEvent(event => {
      if (
        (event.session_id === sessionId || event.session_id === storedId) &&
        ['tool.start', 'tool.complete', 'message.complete', 'session.control.update'].includes(event.type)
      ) {
        schedule()
      }
    })

    const poll = setInterval(refresh, 10_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)

    return () => {
      controller.dispose()
      offWorkspace()
      offEvents?.()

      if (timer) {
        clearTimeout(timer)
      }

      clearInterval(poll)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [controller, gateway, sessionId, storedId])

  return { ...state, refresh: controller.refresh, baseline: controller.baseline }
}
