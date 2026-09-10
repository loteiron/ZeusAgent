import { cn } from '@/lib/utils'

/** Compact Zeus wordmark, also shared with contributed empty-chat views.
 * `fitMin` remains accepted for plugin source compatibility. */
export function Wordmark({
  className,
  text,
  width
}: {
  className?: string
  fitMin?: string
  text: string
  width?: string
}) {
  return (
    <p
      className={cn('z-wordmark break-words text-sm font-semibold tracking-[0.12em] text-(--z-copper-ink)', className)}
      style={width ? { maxWidth: width } : undefined}
    >
      {text}
    </p>
  )
}
