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

The original MIT license in `LICENSE` is preserved verbatim. Copyright notices,
contributor credits, third-party licenses, external service identities and model IDs
remain their respective owners' property. Renaming does not replace these obligations.

ZeusAgent modifications: independent product names and namespaces; separate `.zeus`
state; original lightning mark and theme; stricter goal decisions; atomic goal migration;
finite retry values; workspace-bound verification receipts and baselines; guarded
Hermes data migration; scoped Telegram controls; Windows setup and npm launchers;
and source/runtime distribution protections.

Windows release tools retain their original archives and licenses. Their pinned
source releases are Git for Windows `v2.55.0.windows.5`, Astral uv `0.11.33`,
Node.js `v22.23.2`, and ripgrep `15.2.0`. The runtime manifest contains the official
asset URLs and SHA-256 digests; original licenses remain in each unpacked tool.

No trademark clearance for the name ZeusAgent is claimed. External APIs, hosted services,
model licenses and third-party dependencies retain their own terms and identities.
