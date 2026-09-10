/**
 * Desktop bundles ship precompiled renderer assets. Returning false here tells
 * electron-builder to skip the node_modules collector/install step, which
 * avoids workspace dependency graph explosions and keeps packaging
 * deterministic across environments. Windows releases include a verified
 * source/tool payload; the shared runtime helper installs the pinned Python
 * and locked dependencies on first launch. See `electron/main.ts`.
 */
export default async function beforeBuild() {
  return false
}
