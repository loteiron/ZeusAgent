import { useStore } from '@nanostores/react'
import { useEffect, useId, useMemo } from 'react'

import { useGatewayRequest } from '@/app/gateway/hooks/use-gateway-request'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'
import { migrationMessages } from '@/i18n/hermes-migration'
import { Download } from '@/lib/icons'
import { createHermesMigrationController, type MigrationCategory } from '@/store/hermes-migration'
import { $settingsScopeProfile } from '@/store/settings-scope'

import { SectionHeading, SettingsContent } from './primitives'
import { SettingsProfileScope } from './profile-scope'

export function HermesMigrationSettings() {
  const { locale } = useI18n()
  const m = migrationMessages[locale ?? 'en']
  const profile = useStore($settingsScopeProfile)
  const { gateway } = useGatewayRequest()
  const sourceId = useId()

  const controller = useMemo(
    () =>
      createHermesMigrationController(async (method, params) => {
        if (!gateway) {
          throw new Error('Connect to the agent before scanning Hermes.')
        }

        return gateway.request(method, { ...params, profile })
      }),
    [gateway, profile]
  )

  const state = useStore(controller.state)
  useEffect(() => {
    controller.activate()

    return controller.dispose
  }, [controller])
  const preview = state.preview
  const result = state.result
  const categoryName = (id: string) => m[id as MigrationCategory] ?? id
  const warnings = result?.warnings ?? preview?.warnings ?? []

  return (
    <SettingsContent>
      <div className="mx-auto max-w-3xl space-y-6 py-4" data-testid="hermes-migration">
        <div>
          <SectionHeading icon={Download} title={m.title} />
          <p className="text-sm text-muted-foreground">{m.description}</p>
        </div>
        <SettingsProfileScope />
        <form
          className="space-y-2"
          onSubmit={event => {
            event.preventDefault()
            void controller.scan()
          }}
        >
          <label className="text-sm font-medium" htmlFor={sourceId}>
            {m.source}
          </label>
          <div className="flex flex-wrap gap-2">
            <Input
              className="min-w-0 flex-1 basis-64 font-mono text-xs"
              disabled={state.busy === 'import'}
              id={sourceId}
              onChange={event => controller.setSource(event.target.value)}
              placeholder="~/.hermes"
              value={state.source}
            />
            <Button disabled={Boolean(state.busy) || !gateway} type="submit" variant="outline">
              {state.busy === 'scan' ? m.scanning : m.scan}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{m.sourceHelp}</p>
        </form>
        {state.error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm" role="alert">
            {state.error}
          </div>
        )}
        {preview && (
          <section className="space-y-4">
            <div className="grid items-center gap-2 border-s-2 border-primary bg-primary/5 p-3 sm:grid-cols-[1fr_auto_1fr]">
              <div className="min-w-0">
                <div className="text-xs text-muted-foreground">{m.sourceFound}</div>
                <code className="mt-1 block break-all text-xs" dir="ltr">
                  {preview.source}
                </code>
              </div>
              <Codicon aria-hidden className="text-primary max-sm:rotate-90" name="arrow-right" />
              <div className="min-w-0">
                <div className="text-xs text-muted-foreground">{m.target}</div>
                <code className="mt-1 block break-all text-xs" dir="ltr">
                  {preview.target}
                </code>
              </div>
            </div>
            <fieldset disabled={Boolean(state.busy)}>
              <legend className="mb-2 text-sm font-semibold">{m.preview}</legend>
              <div className="divide-y divide-(--ui-stroke-tertiary) overflow-hidden rounded-md border border-(--ui-stroke-tertiary)">
                {preview.categories.map(category => (
                  <label
                    className="flex cursor-pointer items-center gap-3 px-3 py-3 has-disabled:cursor-default has-disabled:opacity-50"
                    key={category.id}
                  >
                    <input
                      checked={state.selected.includes(category.id)}
                      className="size-4 accent-primary focus-visible:outline-2 focus-visible:outline-primary"
                      disabled={category.count === 0}
                      onChange={event => controller.select(category.id, event.target.checked)}
                      type="checkbox"
                    />
                    <span className="min-w-0 flex-1 text-sm">{categoryName(category.id)}</span>
                    <span className="text-xs text-muted-foreground">
                      {m.count}: <span className="font-mono text-foreground">{category.count}</span>
                      {category.conflicts > 0 && (
                        <span className="ms-3 text-primary">
                          {m.conflicts}: {category.conflicts}
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            {!preview.categories.some(category => category.count > 0) && (
              <p className="text-sm text-muted-foreground">{m.noItems}</p>
            )}
            <div className="space-y-1 text-xs text-muted-foreground">
              <p>{m.preserve}</p>
              <p>{m.credentials}</p>
            </div>
            <Button
              disabled={!state.selected.length || Boolean(state.busy)}
              onClick={() => void controller.importSelected()}
              type="button"
            >
              {state.busy === 'import' ? m.importing : m.import}
            </Button>
          </section>
        )}
        {result && (
          <section aria-live="polite" className="space-y-3 rounded-md border border-primary/30 bg-primary/5 p-4">
            <h3 className="text-sm font-semibold">{m.complete}</h3>
            <code className="block break-all text-xs" dir="ltr">
              {result.target}
            </code>
            <dl className="grid gap-2">
              {Object.keys(result.imported).map(id => (
                <div
                  className="flex flex-wrap items-center justify-between gap-2 border-b border-(--ui-stroke-tertiary) py-2 text-sm"
                  key={id}
                >
                  <dt>{categoryName(id)}</dt>
                  <dd className="text-xs text-muted-foreground">
                    {m.imported}: {result.imported[id]} · {m.skipped}: {result.skipped[id] ?? 0}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="text-xs text-muted-foreground">
              {m.conflicts}: {result.conflicts}
            </p>
            {result.backup_path && (
              <div className="text-xs">
                <span>{m.backup}</span>
                <code className="mt-1 block break-all" dir="ltr">
                  {result.backup_path}
                </code>
              </div>
            )}
            {result.restart_required && <p className="text-sm font-medium">{m.restart}</p>}
          </section>
        )}
        {warnings.length > 0 && (
          <aside className="space-y-2 text-xs text-muted-foreground">
            <h3 className="font-semibold">{m.notice}</h3>
            <ul className="list-disc space-y-1 ps-4">
              {warnings.map(warning => (
                <li className="break-words" key={warning}>
                  {warning}
                </li>
              ))}
            </ul>
          </aside>
        )}
      </div>
    </SettingsContent>
  )
}
