import { Button } from '@/components/ui/button'
import { Check, Loader2 } from '@/lib/icons'
import { cn } from '@/lib/utils'

export function ConnectionLabel({ leaving, text }: { leaving?: boolean; text: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 text-sm font-medium text-primary transition-opacity duration-200 motion-reduce:transition-none',
        leaving ? 'opacity-0' : 'opacity-100'
      )}
      role="status"
    >
      <Check aria-hidden="true" className="size-4" />
      {text}
    </span>
  )
}

export function StartChatButton({
  disabled,
  label,
  loading,
  onClick
}: {
  disabled?: boolean
  label: React.ReactNode
  loading?: boolean
  onClick: () => void
}) {
  return (
    <Button className="min-w-40" disabled={disabled} onClick={onClick} type="button">
      {loading ? <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" /> : null}
      {label}
    </Button>
  )
}
