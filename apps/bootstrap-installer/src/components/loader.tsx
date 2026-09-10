import { LoaderCircle } from 'lucide-react'
import type { ComponentProps } from 'react'

import { cn } from '../lib/utils'

interface LoaderProps extends Omit<ComponentProps<'div'>, 'children'> {
  label?: string
}

export function Loader({ className, label = 'Loading', role = 'status', ...props }: LoaderProps) {
  return (
    <div {...props} aria-label={props['aria-label'] ?? label} className={cn('inline-grid size-10 place-items-center text-primary', className)} role={role}>
      <LoaderCircle aria-hidden="true" className="size-5 animate-spin motion-reduce:animate-none" strokeWidth={1.8} />
    </div>
  )
}