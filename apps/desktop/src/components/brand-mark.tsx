import { cn } from '@/lib/utils'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// ZeusAgent's original lightning mark, shared with native application icons.
// Fills the tile (softly rounded); size via className (default size-14).
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'inline-flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-xl',
        className
      )}
      {...props}
    >
      <img alt="ZeusAgent" className="size-full object-contain" src={assetPath('zeus-mark.svg')} />
    </span>
  )
}
