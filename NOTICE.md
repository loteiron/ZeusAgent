# ZeusAgent — provenance and notices

ZeusAgent is an independent derivative of **Hermes Agent**, originally developed by
**Nous Research and its contributors**. It is not an official Nous Research release.

Upstream: https://github.com/NousResearch/hermes-agent

Source baseline: `2237be355906fbe6065ce1815711eee52b2d646e` (upstream 0.21.1).

The 0.22.0 core recovery changes adapt budget-checkpoint, authentication-result,
oversized-image, clarification-retention, and bounded continuation/restart behavior
from the upstream snapshot
`f97a4102dd3864eed0c85132850ce7e06f13e09a`:
https://github.com/NousResearch/hermes-agent/commit/f97a4102dd3864eed0c85132850ce7e06f13e09a

The September 12 source update additionally adapts these upstream fixes, with
Zeus namespace changes and regression coverage:

- Custom-provider automatic context-length feedback, by teknium1:
  https://github.com/NousResearch/hermes-agent/commit/e8016a18c13a9d5623e7588ae1bb8e7afd659b62
- Telegram command-menu Unicode dash normalization, by nikkoxgonzales:
  https://github.com/NousResearch/hermes-agent/commit/75ade17617aab749b8d3979eaaf20b0447f57352
- Skills guard DNS-exfiltration false-positive correction, by Teknium:
  https://github.com/NousResearch/hermes-agent/commit/596bd8fec6108d5e91e313c2225f5bf0df0051b8

The September 13 integration reviews and ports all 181 commits after
`53c57871d67ee7d2202861aacc4ea0ef6ef93112` through
`d595e636c83aa0b9606d4e914e1140ae9c796897`. Git preserves each upstream author,
co-author trailers, and an `Upstream-Commit` reference. `upstream-sync.json`
records the exact range and the preceding Zeus revision.

This is an incremental adaptation, not a claim that every earlier upstream
change is present. Necessary shared-gateway lifecycle/status and scoped database teardown helpers were
adapted from the same target snapshot. Hermes logo-only changes are represented
by attributed empty commits because Zeus already has its own mark; terminal
alignment is verified against Zeus's layout. The installer mock context-size
change is applied to Zeus's existing Desktop mock launcher rather than adding
an unused second fixture. Inherited automation remains inactive under
`.github/upstream-workflows/`; the Zeus upstream-integration workflow only runs
tests in GitHub-hosted environments and does not deploy to user servers.

The retained shell installer exposes helper contracts only; source installation
uses `scripts/setup_zeus.py` and reuses the supported interpreter running it.
Published release installers keep their separately pinned managed runtime.

The September 15 source update adapts three selected Hermes changes from the
reviewed upstream snapshot `1ad89ac018f26a4f21817ebf37bb09f508656d63`:

- Responsive `process_manage` waits during steering, by Teknium, itself a port
  of MoonshotAI/kimi-code#3697:
  https://github.com/NousResearch/hermes-agent/commit/cbd4492f1fc3b336619a7871b5dae94b86975693
- Browser and computer-use caches scoped to the served profile, by teknium1:
  https://github.com/NousResearch/hermes-agent/commit/71cebc63488c017635994bd92d5a5c98f08acd84
  Zeus also scopes the older computer-use call locks and approval caches.
- Native main-model vision availability for image and browser tools, by teknium1:
  https://github.com/NousResearch/hermes-agent/commit/53183d50167d642c337232b44e4c94e718f0e620

The remaining commits in that newer range are not claimed as integrated.

The original MIT license in `LICENSE` is preserved verbatim. Copyright notices,
contributor credits, third-party licenses, external service identities and model IDs
remain their respective owners' property. Renaming does not replace these obligations.

ZeusAgent modifications: independent product names and namespaces; separate `.zeus`
state; original lightning mark and theme; stricter goal decisions; atomic goal migration;
finite retry values; workspace-bound verification receipts and baselines; guarded
Hermes data migration; scoped Telegram controls; Windows setup, Ubuntu packages
and shared npm launchers;
and source/runtime distribution protections.

Windows release tools retain their original archives and licenses. Their pinned
source releases are Git for Windows `v2.55.0.windows.5`, Astral uv `0.11.33`,
Node.js `v22.23.2`, and ripgrep `15.2.0`. The runtime manifest contains the official
asset URLs and SHA-256 digests; original licenses remain in each unpacked tool.

Linux releases bundle the original Astral uv `0.11.33` and Node.js `v22.23.2`
archives with their licenses. Python is installed as a private managed runtime;
Git and ripgrep remain distribution-managed system packages. Linux source archives
preserve the reviewed Git executable modes and include source/build manifests.

No trademark clearance for the name ZeusAgent is claimed. External APIs, hosted services,
model licenses and third-party dependencies retain their own terms and identities.
