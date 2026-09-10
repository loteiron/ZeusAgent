/**
 * after-pack.mjs — electron-builder afterPack hook.
 *
 * Stamps the ZeusAgent icon + identity onto the packed Windows ZeusAgent.exe via
 * rcedit (delegated to set-exe-identity.mjs). This runs for EVERY packed build
 * — first install, `zeus desktop`, the installer's --update rebuild, and a
 * dev's manual `npm run pack` — so the branded exe can never silently revert
 * to the stock "Electron" icon/name (the bug when the stamp lived only in
 * install.ps1, which the update path doesn't use).
 *
 * On Linux, make the staged CLI launcher executable before FPM records its
 * permissions in the .deb. Windows PE identity stamping remains best-effort.
 *
 * electron-builder passes a context with:
 *   - electronPlatformName: 'win32' | 'darwin' | 'linux'
 *   - appOutDir:            the unpacked app directory for this target
 *   - packager.appInfo.productFilename: the exe basename (e.g. 'ZeusAgent')
 */

import { chmod } from 'node:fs/promises'
import path from 'node:path'

import { stampExeIdentity } from './set-exe-identity.mjs'

export default async function afterPack(context) {
  if (context.electronPlatformName === 'linux') {
    // The copy staged for FPM must be executable even after a Windows checkout.
    await chmod(path.join(context.appOutDir, 'resources', 'cli', 'zeus'), 0o755)
    return
  }
  if (context.electronPlatformName !== 'win32') {
    return
  }

  const productName = context.packager?.appInfo?.productFilename || 'ZeusAgent'
  const exe = path.join(context.appOutDir, `${productName}.exe`)
  const desktopRoot = path.resolve(import.meta.dirname, '..')

  try {
    await stampExeIdentity(exe, desktopRoot)
  } catch (err) {
    // Never fail the build over a cosmetic stamp.
    console.warn(`[after-pack] exe identity stamp failed (${err.message}); ZeusAgent.exe keeps the stock Electron icon`)
  }
}
