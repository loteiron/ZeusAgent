import { Loader2 } from 'lucide-react'

import { cn } from '../lib/utils'

/** Primary installer action. State and native button behavior are unchanged. */
export function HackeryButton({
  className,
  label,
  loading,
  ...props
}: Omit<React.ComponentProps<'button'>, 'children'> & { label: React.ReactNode; loading?: boolean }) {
  return (
    <button
      {...props}
      className={cn(
        'inline-flex cursor-pointer items-center gap-2 rounded-lg border border-transparent bg-primary px-6 py-3',
        'font-sans text-sm font-semibold text-primary-foreground',
        'transition-colors duration-150 hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring',
        'disabled:pointer-events-none disabled:opacity-50',
        className
      )}
      type="button"
    >
      {loading ? <Loader2 className="size-3 animate-spin" /> : null}
      <span>{label}</span>
    </button>
  )
}
