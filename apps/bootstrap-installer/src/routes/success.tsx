import { AlertCircle } from 'lucide-react'
import { useState } from 'react'

import { BrandMark } from '../components/brand-mark'
import { HackeryButton } from '../components/hackery-button'
import { launchZeusAgentDesktop } from '../store'

/*
 * Success screen retains launch errors inline.


 *
 * Launching the desktop can fail (e.g. Stage-Desktop was skipped and
 * ZeusAgent.exe doesn't exist). We catch the Tauri error and surface it
 * inline rather than silently doing nothing — the previous version
 * had `onClick={() => void launchZeusAgentDesktop()}` which swallowed
 * the rejection and left the user staring at an unresponsive button.
 */
export default function Success() {
  const [error, setError] = useState<string | null>(null)
  const [launching, setLaunching] = useState(false)

  async function handleLaunch() {
    setError(null)
    setLaunching(true)

    try {
      await launchZeusAgentDesktop()
      // On success the installer exits — control never returns here.
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      setLaunching(false)
    }
  }

  return (
    <div className="zeus-fade-in flex h-full flex-col items-center justify-center gap-8 px-12 py-10">
      <div className="w-full max-w-2xl min-w-0 text-center">
        <BrandMark className="mx-auto mb-7 size-16" /><h1 className="installer-heading">Your workspace is ready</h1>

        <p className="m-0 text-center text-base leading-normal tracking-tight text-muted-foreground">
          You can launch from here, or any time from your terminal with{' '}
          <code className="font-mono text-sm text-foreground/80">zeus desktop</code>.
        </p>
      </div>

      <HackeryButton
        disabled={launching}
        label={launching ? 'Launching' : 'Launch'}
        loading={launching}
        onClick={() => void handleLaunch()}
      />

      {error && (
        <div className="flex max-w-2xl items-start gap-2 text-sm" role="alert">
          <AlertCircle className="mt-0.5 shrink-0 text-destructive" size={16} />
          <div className="min-w-0">
            <div className="font-medium text-destructive">Couldn&rsquo;t launch the desktop app</div>
            <div className="mt-0.5 text-muted-foreground">{error}</div>
          </div>
        </div>
      )}
    </div>
  )
}
