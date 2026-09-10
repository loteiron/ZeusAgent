# ZeusAgent for Windows

Install the `.tgz` package from a ZeusAgent GitHub release:

```powershell
npm install --global https://github.com/loteiron/ZeusAgent/releases/download/v0.22.0/loteiron-zeus-agent-0.22.0.tgz
zeus
```

Run `zeus` from any project directory in CMD or PowerShell. Node.js 22 or newer
and Windows x64 are required. The first launch downloads the release's verified
source archive, installs an isolated Python runtime and locked dependencies,
and then starts the terminal agent. It can take a few minutes and requires an
internet connection. Later launches reuse that runtime.

Use `zeus setup` to configure a provider, `zeus gateway run` for messaging,
or `zeus --desktop` to open the separately installed ZeusAgent desktop app.
The Windows installer is available on the same release page.

Your configuration and conversations remain in your ZeusAgent profile when the
npm package is updated or removed. npm manages its standard global command
directory; reopen your terminal after installing Node.js. If PowerShell blocks
its npm-generated script under a restrictive execution policy, use `zeus.cmd`.

This package uses no npm install scripts and has no npm dependencies. Runtime
installation happens only when you invoke `zeus`.
