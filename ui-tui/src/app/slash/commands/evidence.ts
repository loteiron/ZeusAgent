import type { VerificationStatusResponse } from '../../../gatewayTypes.js'
import type { SlashCommand } from '../types.js'

export const evidenceCommands: SlashCommand[] = [
  {
    name: 'evidence',
    help: 'inspect workspace checks, failures, freshness and baseline changes (read only)',
    run: (arg, ctx) => {
      if (arg.trim() && arg.trim().toLowerCase() !== 'status') {
        return ctx.transcript.sys('Usage: /evidence [status]. This command only reads existing checks.')
      }

      if (!ctx.sid) {
        return ctx.transcript.sys('No active session. Choose a workspace session before inspecting evidence.')
      }

      ctx.transcript.sys('Inspecting workspace evidence…')

      return ctx.gateway
        .rpc<VerificationStatusResponse>('verification.status', { session_id: ctx.sid })
        .then(
          ctx.guarded(response => {
            const report = response.verification

            if (!report || !Array.isArray(report.checks)) {
              return ctx.transcript.sys('Verification evidence is unavailable. Run /evidence to retry.')
            }

            const lines = [
              `Verification: ${report.status}`,
              `Workspace: ${report.workspace?.root || report.root || '(unavailable)'}`,
              `Session: ${report.session_id || ctx.sid}`
            ]

            if (report.workspace?.reason) {
              lines.push(report.workspace.reason)
            }

            if (report.summary) {
              lines.push(
                `Checks: ${report.summary.total} total · ${report.summary.passed} passed · ${report.summary.failed} failed · ${report.summary.stale} stale · ${report.summary.unknown} unknown`
              )
            }

            for (const check of report.checks) {
              lines.push(
                '',
                `${check.status.toUpperCase()} | ${check.freshness} | ${check.comparison} | ${check.scope}`,
                check.command,
                `Exit: ${check.exit_code ?? 'pending'} · ${check.created_at} · ${check.cwd}`
              )

              if (check.output_summary) {
                lines.push(check.output_summary)
              }
            }

            if (!report.checks.length) {
              lines.push(
                '',
                'No recorded checks for this workspace session. Run your project checks, then use /evidence again.'
              )
            }

            const changed = report.workspace?.changed_paths ?? []

            if (changed.length) {
              lines.push('', 'Changed paths:', ...changed.map(file => `  ${file}`))
            }

            if (report.baseline) {
              lines.push('', `Baseline: ${report.baseline.created_at} · ${report.baseline.check_count} checks`)
            }

            ctx.transcript.page(lines.join('\n'), 'Evidence')
          })
        )
        .catch(ctx.guardedErr)
    }
  }
]
