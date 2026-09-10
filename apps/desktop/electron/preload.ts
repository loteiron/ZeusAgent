import { contextBridge, ipcRenderer, webFrame, webUtils } from 'electron'

// Which translucency the OS can back. Asked synchronously because the renderer
// needs it before its first paint, and answered by main because deciding it
// needs `os.release()` — a sandboxed preload may only require electron, events,
// timers and url, so importing node:os here throws before contextBridge runs
// and takes the ENTIRE bridge down with it (window.zeusDesktop undefined =>
// "Desktop IPC bridge is unavailable"). No reply means no glass, which degrades
// to an ordinary opaque window rather than a page thinned over nothing.
const translucencySupport = ipcRenderer.sendSync('zeus:translucency:support')
const hudWindowing = ipcRenderer.sendSync('zeus:hud:windowing')
const hudNativeDrag = hudWindowing?.nativeDrag === true
const launchFlags = ipcRenderer.sendSync('zeus:launch-flags')

contextBridge.exposeInMainWorld('zeusDesktop', {
  glassSupported: translucencySupport?.glass === true,
  translucencySupported: translucencySupport?.translucency === true,
  // Launch-flag fact: the app was started with --local, so the renderer may
  // show the local-models surfaces. Static for the window's lifetime.
  localModelsEnabled: launchFlags?.localModels === true,
  getConnection: (profile, opts) => ipcRenderer.invoke('zeus:connection', profile, opts),
  // Registry-scoped backend resolution: { connectionId, profile } → descriptor.
  getConnectionFor: payload => ipcRenderer.invoke('zeus:connection:for', payload),
  getProfileRoutes: profiles => ipcRenderer.invoke('zeus:plugin-profile-routes', profiles),
  revalidateConnection: () => ipcRenderer.invoke('zeus:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('zeus:backend:touch', profile),
  getPoolLimits: () => ipcRenderer.invoke('zeus:pool-limits:get'),
  setPoolLimits: limits => ipcRenderer.invoke('zeus:pool-limits:set', limits),
  getGatewayWsUrl: profile => ipcRenderer.invoke('zeus:gateway:ws-url', profile),
  // Registry-scoped fresh WS URL: { connectionId, profile } → result shape of
  // getGatewayWsUrl, minted against that connection's backend.
  getGatewayWsUrlFor: payload => ipcRenderer.invoke('zeus:gateway:ws-url-for', payload),
  // Union agent roster across every registered connection.
  getAgentRoster: () => ipcRenderer.invoke('zeus:agents:roster'),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('zeus:window:openSession', sessionId, opts),
  openSessionInTerminal: (sessionId, opts) => ipcRenderer.invoke('zeus:window:openInTerminal', sessionId, opts),
  openWindow: () => ipcRenderer.invoke('zeus:window:openInstance'),
  openBrowserWindow: tabId => ipcRenderer.invoke('zeus:window:openBrowser', tabId),
  onBrowserPopoutClosed: callback => {
    const listener = (_event, tabId) => callback(tabId)
    ipcRenderer.on('zeus:browser-popout:closed', listener)

    return () => ipcRenderer.removeListener('zeus:browser-popout:closed', listener)
  },
  claimAmbientCue: key => ipcRenderer.invoke('zeus:ambient:claim', key),
  wakeIndicator: {
    getState: () => ipcRenderer.invoke('zeus:wake-indicator:get'),
    setState: state => ipcRenderer.send('zeus:wake-indicator:set', state),
    onState: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('zeus:wake-indicator:state', listener)

      return () => ipcRenderer.removeListener('zeus:wake-indicator:state', listener)
    }
  },
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('zeus:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('zeus:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('zeus:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('zeus:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('zeus:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('zeus:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('zeus:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeus:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('zeus:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeus:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('zeus:pet-overlay:control', listener)
    }
  },
  // HUD mode: the chrome-free floating chat. A full app renderer (own gateway)
  // sized as a floating bar, so it mounts the real composer. Main owns the
  // window; `onChanged` keeps every window's toggle truthful.
  hud: {
    nativeDrag: hudNativeDrag,
    windowing: {
      clientPlacement: hudWindowing?.clientPlacement !== false,
      controlDrag: hudWindowing?.controlDrag === true,
      nativeDrag: hudNativeDrag,
      solid: hudWindowing?.solid === true,
      workspaceTransfer: hudWindowing?.workspaceTransfer === true
    },
    open: request => ipcRenderer.invoke('zeus:hud:open', request),
    close: () => ipcRenderer.invoke('zeus:hud:close'),
    setIgnoreMouse: ignore => ipcRenderer.send('zeus:hud:ignore-mouse', ignore),
    beginMove: () => ipcRenderer.send('zeus:hud:begin-move'),
    endMove: () => ipcRenderer.send('zeus:hud:end-move'),
    moveBy: delta => ipcRenderer.send('zeus:hud:move-by', delta),
    setWorkspaceTransfer: transferring => ipcRenderer.send('zeus:hud:workspace-transfer', transferring),
    setBounds: bounds => ipcRenderer.send('zeus:hud:set-bounds', bounds),
    resetLayout: () => ipcRenderer.invoke('zeus:hud:reset-layout'),
    // Whether the band covers the window below the bar. Main pairs it with the
    // user's translucency setting to decide the native frost (macOS vibrancy /
    // Windows 11 DWM backdrop) — see hudFrostFor.
    setFrost: showing => ipcRenderer.invoke('zeus:hud:frost', showing),
    // The HUD tells main which session it is on; main hands that back to the
    // app window when the HUD closes, so the app can re-home onto it.
    setSession: sessionId => ipcRenderer.send('zeus:hud:session', sessionId),
    onGoto: callback => {
      const listener = (_event, sessionId) => callback(sessionId)
      ipcRenderer.on('zeus:hud:goto', listener)

      return () => ipcRenderer.removeListener('zeus:hud:goto', listener)
    },
    onChanged: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('zeus:hud:changed', listener)

      return () => ipcRenderer.removeListener('zeus:hud:changed', listener)
    },
    // Linux only, and silent elsewhere: where the cursor is, in page
    // coordinates, or null when it has left the window. Stands in for the
    // mousemove that `setIgnoreMouseEvents(true, { forward: true })` delivers on
    // macOS and Windows but not here.
    onCursor: callback => {
      const listener = (_event, point) => callback(point)
      ipcRenderer.on('zeus:hud:cursor', listener)

      return () => ipcRenderer.removeListener('zeus:hud:cursor', listener)
    },
    // Main's game-overlay watch: whether a fullscreen app (a game) is under
    // the HUD, so the renderer can step back to the low-opacity overlay
    // treatment while one owns the screen.
    onGameOverlay: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('zeus:hud:game-overlay', listener)

      return () => ipcRenderer.removeListener('zeus:hud:game-overlay', listener)
    }
  },
  // Quick Entry: the global-hotkey mini composer window. Main owns the OS
  // shortcut + the persisted preference; the quick window only captures text
  // and hands it back, and the primary renderer submits it through the normal
  // prompt path.
  quickEntry: {
    getSettings: () => ipcRenderer.invoke('zeus:quick-entry:settings:get'),
    setSettings: patch => ipcRenderer.invoke('zeus:quick-entry:settings:set', patch),
    submit: payload => ipcRenderer.send('zeus:quick-entry:submit', payload),
    dismiss: () => ipcRenderer.send('zeus:quick-entry:dismiss'),
    // Primary renderer → main → quick window: gateway connection state + the
    // recent-session options the target picker offers. Main caches the latest
    // payload so a freshly spawned quick window starts from truth.
    pushState: payload => ipcRenderer.send('zeus:quick-entry:state', payload),
    // Quick window subscribes to those pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeus:quick-entry:state', listener)

      return () => ipcRenderer.removeListener('zeus:quick-entry:state', listener)
    },
    // Main → primary renderer: a submit captured by the quick window.
    onSubmit: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeus:quick-entry:submit', listener)

      return () => ipcRenderer.removeListener('zeus:quick-entry:submit', listener)
    },
    // Main → quick window: you were just summoned (reset draft + refocus).
    onShown: callback => {
      const listener = () => callback()
      ipcRenderer.on('zeus:quick-entry:shown', listener)

      return () => ipcRenderer.removeListener('zeus:quick-entry:shown', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('zeus:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('zeus:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('zeus:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('zeus:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('zeus:connection-config:test', payload),
  // Opt-in OS-keychain encryption for stored gateway secrets (default off —
  // see secret-storage-policy.ts). get never touches the OS keychain.
  getSecretStorageEncryption: () => ipcRenderer.invoke('zeus:secret-storage:get'),
  setSecretStorageEncryption: (on: boolean) => ipcRenderer.invoke('zeus:secret-storage:set', on),
  // v2 multi-connection registry: named agent sources (local / remote / cloud / ssh).
  connections: {
    list: () => ipcRenderer.invoke('zeus:connections:list'),
    save: payload => ipcRenderer.invoke('zeus:connections:save', payload),
    remove: id => ipcRenderer.invoke('zeus:connections:remove', id),
    setPrimary: id => ipcRenderer.invoke('zeus:connections:set-primary', id),
    setLaunchMode: mode => ipcRenderer.invoke('zeus:connections:set-launch-mode', mode),
    setLastUsed: id => ipcRenderer.invoke('zeus:connections:set-last-used', id),
    test: id => ipcRenderer.invoke('zeus:connections:test', id),
    updateManaged: id => ipcRenderer.invoke('zeus:connections:update-managed', id),
    // Fan out `zeus update` to every eligible registered connection.
    // Optional excludeIds skips rows the caller updates through another path.
    updateAll: options => ipcRenderer.invoke('zeus:connections:update-all', options),
    // Registry lifecycle push (main → renderer): a connection was removed or
    // materially edited, so secondaries scoped to it must be disposed (and,
    // for edits, re-dialed at the new target).
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeus:connections:changed', listener)

      return () => ipcRenderer.removeListener('zeus:connections:changed', listener)
    }
  },
  sshConfigHosts: () => ipcRenderer.invoke('zeus:ssh-config:hosts'),
  sshResolveHost: host => ipcRenderer.invoke('zeus:ssh-config:resolve', host),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('zeus:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('zeus:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('zeus:connection-config:oauth-logout', remoteUrl),
  // ZeusAgent Cloud: one portal login powers discovery + silent per-agent sign-in
  // (cloud-auto-discovery Phase 3).
  cloud: {
    status: () => ipcRenderer.invoke('zeus:cloud:status'),
    login: () => ipcRenderer.invoke('zeus:cloud:login'),
    logout: () => ipcRenderer.invoke('zeus:cloud:logout'),
    discover: org => ipcRenderer.invoke('zeus:cloud:discover', org),
    agentSignIn: dashboardUrl => ipcRenderer.invoke('zeus:cloud:agent-sign-in', dashboardUrl)
  },
  profile: {
    get: () => ipcRenderer.invoke('zeus:profile:get'),
    remember: name => ipcRenderer.invoke('zeus:profile:remember', name),
    set: name => ipcRenderer.invoke('zeus:profile:set', name)
  },
  api: request => ipcRenderer.invoke('zeus:api', request),
  notify: payload => ipcRenderer.invoke('zeus:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('zeus:requestMicrophoneAccess'),
  readWindowBelow: () => ipcRenderer.invoke('zeus:window:readBelow'),
  readFileDataUrl: filePath => ipcRenderer.invoke('zeus:readFileDataUrl', filePath),
  readFileDataUrlForAttach: filePath => ipcRenderer.invoke('zeus:readFileDataUrlForAttach', filePath),
  dataUrlReadMax: {
    get: () => ipcRenderer.invoke('zeus:data-url-read-max:get'),
    set: maxMb => ipcRenderer.invoke('zeus:data-url-read-max:set', maxMb)
  },
  readFileText: filePath => ipcRenderer.invoke('zeus:readFileText', filePath),
  readPluginSource: (filePath: string) => ipcRenderer.invoke('zeus:readPluginSource', filePath),
  selectPaths: options => ipcRenderer.invoke('zeus:selectPaths', options),
  selectSavePath: options => ipcRenderer.invoke('zeus:selectSavePath', options),
  writeClipboard: text => ipcRenderer.invoke('zeus:writeClipboard', text),
  readClipboard: () => ipcRenderer.invoke('zeus:readClipboard'),
  saveGatewayFile: payload => ipcRenderer.invoke('zeus:saveGatewayFile', payload),
  saveImageFromUrl: url => ipcRenderer.invoke('zeus:saveImageFromUrl', url),
  contextMenuEdit: command => ipcRenderer.invoke('zeus:context-menu:edit', command),
  contextMenuCopyImage: () => ipcRenderer.invoke('zeus:context-menu:copy-image'),
  contextMenuSpellcheck: action => ipcRenderer.invoke('zeus:context-menu:spellcheck', action),
  contextMenuGuestAddWord: payload => ipcRenderer.invoke('zeus:context-menu:guest-add-word', payload),
  onContextMenuSpellcheck: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:context-menu-spellcheck', listener)

    return () => ipcRenderer.removeListener('zeus:context-menu-spellcheck', listener)
  },
  saveImageBuffer: (data, ext, name) => ipcRenderer.invoke('zeus:saveImageBuffer', { data, ext, name }),
  capturePreview: payload => ipcRenderer.invoke('zeus:capturePreview', payload),
  saveClipboardImage: () => ipcRenderer.invoke('zeus:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('zeus:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('zeus:watchPreviewFile', url),
  watchDirectory: dir => ipcRenderer.invoke('zeus:watchDirectory', dir),
  stopPreviewFileWatch: id => ipcRenderer.invoke('zeus:stopPreviewFileWatch', id),
  setActiveWork: payload => ipcRenderer.send('zeus:active-work', payload),
  setTitleBarTheme: payload => ipcRenderer.send('zeus:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('zeus:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('zeus:translucency', payload),
  setKeepAwake: on => ipcRenderer.send('zeus:keep-awake', on),
  setDisableF12: blocked => ipcRenderer.send('zeus:devtools:disable-f12', blocked),
  setPreviewShortcutActive: active => ipcRenderer.send('zeus:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('zeus:openExternal', url),
  mcpOauth: {
    // One-shot loopback listener for MCP OAuth against remote backends: bind
    // on this machine, hand redirectUri to mcp.servers.oauth.start, then wait
    // for the provider redirect and relay code/state via oauth.callback.
    listen: () => ipcRenderer.invoke('zeus:mcp-oauth:listen'),
    wait: (id, timeoutMs) => ipcRenderer.invoke('zeus:mcp-oauth:wait', id, timeoutMs),
    cancel: id => ipcRenderer.invoke('zeus:mcp-oauth:cancel', id)
  },
  openPreviewInBrowser: url => ipcRenderer.invoke('zeus:openPreviewInBrowser', url),
  reachPreviewUrl: url => ipcRenderer.invoke('zeus:preview:reach', url),
  setActiveConnectionRoute: route => ipcRenderer.send('zeus:connection:active-route', route),
  fetchLinkTitle: url => ipcRenderer.invoke('zeus:fetchLinkTitle', url),
  resolveFavicon: url => ipcRenderer.invoke('zeus:resolveFavicon', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('zeus:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('zeus:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('zeus:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('zeus:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('zeus:zoom:get'),
    // Synchronous zoom factor (1 = 100%). Coordinate math needs it in the
    // same tick as the event it converts, so no IPC round-trip here.
    factor: () => webFrame.getZoomFactor(),
    setPercent: percent => ipcRenderer.send('zeus:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeus:zoom:changed', listener)

      return () => ipcRenderer.removeListener('zeus:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('zeus:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('zeus:logs:recent'),
  // Fire-and-forget: persists a renderer error-boundary catch (with component
  // stack) to desktop.log so crashes survive the window (#79428).
  reportRendererError: report => ipcRenderer.send('zeus:logs:renderer-error', report),
  readDir: dirPath => ipcRenderer.invoke('zeus:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('zeus:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('zeus:fs:reveal', targetPath),
  openDir: dirPath => ipcRenderer.invoke('zeus:fs:openDir', dirPath),
  desktopPluginsRoot: () => ipcRenderer.invoke('zeus:fs:desktopPluginsRoot'),
  logsRoot: () => ipcRenderer.invoke('zeus:fs:logsRoot'),
  agentPluginsRoot: () => ipcRenderer.invoke('zeus:fs:agentPluginsRoot'),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('zeus:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('zeus:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('zeus:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('zeus:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('zeus:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('zeus:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('zeus:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('zeus:git:branchList', repoPath),
    baseBranchList: repoPath => ipcRenderer.invoke('zeus:git:baseBranchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('zeus:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('zeus:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('zeus:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('zeus:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('zeus:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('zeus:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('zeus:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('zeus:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('zeus:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('zeus:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('zeus:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('zeus:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('zeus:git:review:shipInfo', repoPath),
      prList: (repoPath, branches, numbers) =>
        ipcRenderer.invoke('zeus:git:review:prList', repoPath, branches, numbers),
      fetchPrComment: (repoPath, url) => ipcRenderer.invoke('zeus:git:review:fetchPrComment', repoPath, url),
      createPr: repoPath => ipcRenderer.invoke('zeus:git:review:createPr', repoPath)
    }
  },
  terminal: {
    attach: id => ipcRenderer.invoke('zeus:terminal:attach', id),
    cwd: id => ipcRenderer.invoke('zeus:terminal:cwd', id),
    dispose: id => ipcRenderer.invoke('zeus:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('zeus:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('zeus:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('zeus:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `zeus:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `zeus:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeus:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('zeus:close-preview-requested', listener)
  },
  onPreviewNav: callback => {
    const listener = (_event, command) => callback(command)
    ipcRenderer.on('zeus:preview-nav', listener)

    return () => ipcRenderer.removeListener('zeus:preview-nav', listener)
  },
  onOpenFolderRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeus:open-folder-requested', listener)

    return () => ipcRenderer.removeListener('zeus:open-folder-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeus:open-updates', listener)

    return () => ipcRenderer.removeListener('zeus:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:deep-link', listener)

    return () => ipcRenderer.removeListener('zeus:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('zeus:deep-link-ready'),
  probePluginRepo: payload => ipcRenderer.invoke('zeus:plugin:probe', payload),
  installDesktopPlugin: payload => ipcRenderer.invoke('zeus:plugin:installDesktop', payload),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:window-state-changed', listener)

    return () => ipcRenderer.removeListener('zeus:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('zeus:focus-session', listener)

    return () => ipcRenderer.removeListener('zeus:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:notification-action', listener)

    return () => ipcRenderer.removeListener('zeus:notification-action', listener)
  },
  onNotificationActivate: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:notification-activate', listener)

    return () => ipcRenderer.removeListener('zeus:notification-activate', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('zeus:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:backend-exit', listener)

    return () => ipcRenderer.removeListener('zeus:backend-exit', listener)
  },
  // Soft gateway-mode apply finished tearing down the primary backend. Renderer
  // should wipe session lists + re-dial without a window reload.
  onConnectionApplied: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeus:connection:applied', listener)

    return () => ipcRenderer.removeListener('zeus:connection:applied', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeus:power-resume', listener)

    return () => ipcRenderer.removeListener('zeus:power-resume', listener)
  },
  // AC ↔ battery transitions; renderers slow their backstop polls on battery.
  getOnBattery: () => ipcRenderer.invoke('zeus:power-battery:get'),
  onBatteryChanged: callback => {
    const listener = (_event, onBattery) => callback(Boolean(onBattery))
    ipcRenderer.on('zeus:power-battery', listener)

    return () => ipcRenderer.removeListener('zeus:power-battery', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:boot-progress', listener)

    return () => ipcRenderer.removeListener('zeus:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('zeus:bootstrap:get'),
  continueBootstrapLocal: () => ipcRenderer.invoke('zeus:bootstrap:continue-local'),
  recycleBackend: profile => ipcRenderer.invoke('zeus:backend:recycle', profile),
  resetBootstrap: () => ipcRenderer.invoke('zeus:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('zeus:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('zeus:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeus:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('zeus:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('zeus:version'),
  relaunchApp: () => ipcRenderer.invoke('zeus:app:relaunch'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('zeus:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('zeus:uninstall:summary'),
    run: mode => ipcRenderer.invoke('zeus:uninstall:run', { mode })
  },
  updates: {
    check: () => ipcRenderer.invoke('zeus:updates:check'),
    apply: opts => ipcRenderer.invoke('zeus:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('zeus:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('zeus:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeus:updates:progress', listener)

      return () => ipcRenderer.removeListener('zeus:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('zeus:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('zeus:vscode-theme:search', query)
  },
  // Find-in-page (Ctrl/Cmd+F): delegates to Electron's
  // webContents.findInPage on the IPC sender's window so a Cmd+F pressed
  // in a secondary session window searches THAT window, not the primary.
  // `onFoundInPage` returns the unsubscribe fn; the renderer wires it via
  // `initFindInPageListener` in store/find-in-page.ts and tears it down
  // when the FindBar unmounts.
  findInPage: (query, options) => ipcRenderer.invoke('zeus:find-in-page', query, options),
  stopFindInPage: () => ipcRenderer.invoke('zeus:stop-find-in-page'),
  onFoundInPage: callback => {
    const listener = (_event, result) => callback(result)
    ipcRenderer.on('zeus:found-in-page', listener)

    return () => ipcRenderer.removeListener('zeus:found-in-page', listener)
  },
  // Main-process `before-input-event` forwards Ctrl/Cmd+F here so renderer
  // can open the FindBar even when the GTK compositor has already grabbed
  // the chord at the windowing layer (#81727).
  onOpenFindBarRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeus:open-find-bar', listener)

    return () => ipcRenderer.removeListener('zeus:open-find-bar', listener)
  }
})
