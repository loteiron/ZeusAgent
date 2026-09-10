import { BrandMark } from '../components/brand-mark'
import { HackeryButton } from '../components/hackery-button'
import { startInstall } from '../store'

export default function Welcome() {
  return (
    <div className="zeus-fade-in flex h-full flex-col items-center justify-center gap-7 px-10 py-8">
      <BrandMark className="size-20" />
      <div className="w-full max-w-xl text-center">
        <p className="installer-kicker mb-4">ZEUS / SETUP</p>
        <h1 className="installer-heading">Set up your workspace</h1>
        <p className="mx-auto max-w-md text-base leading-relaxed text-muted-foreground">
          Install ZeusAgent and its desktop app on this computer. Setup downloads the required components and takes a few minutes.
        </p>
      </div>
      <HackeryButton label="Install ZeusAgent" onClick={() => void startInstall()} />
    </div>
  )
}