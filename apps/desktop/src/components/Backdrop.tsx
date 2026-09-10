import { useStore } from '@nanostores/react'

import { $backdrop } from '@/store/backdrop'

export function Backdrop() {
  const on = useStore($backdrop)

  if (!on) {
    return null
  }

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 z-2 overflow-hidden text-(--z-storm) opacity-[0.055]"
    >
      <svg className="absolute end-0 top-0 h-full w-auto" fill="none" viewBox="0 0 900 1000">
        <path
          d="M900 80H500L280 300H680L340 640H900M900 120H520L380 260H780L440 600H900M900 160H540L480 220H880L540 560H900"
          stroke="currentColor"
          strokeWidth="1"
        />
      </svg>
    </div>
  )
}
