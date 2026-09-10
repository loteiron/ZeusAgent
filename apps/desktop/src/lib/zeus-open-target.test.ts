import { describe, expect, it } from 'vitest'

import {
  normalizeZeusAgentOpenString,
  pathFromZeusAgentDeepLink,
  pathFromOpenDeepLink,
  resolveZeusAgentOpenPath
} from './zeus-open-target'

describe('normalizeZeusAgentOpenString', () => {
  it('accepts hash-router paths and strips a leading hash', () => {
    expect(normalizeZeusAgentOpenString('/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeZeusAgentOpenString('#/index-network/intent/1')).toBe('/index-network/intent/1')
  })

  it('maps plugin-scoped zeus:// deep links to the same path', () => {
    expect(normalizeZeusAgentOpenString('zeus://index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeZeusAgentOpenString('zeus://index-network/intent/1?focus=true')).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('maps zeus://open/… deep links by stripping the open host', () => {
    expect(normalizeZeusAgentOpenString('zeus://open/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeZeusAgentOpenString('zeus://open/settings/plugins')).toBe('/settings/plugins')
  })

  it('rejects reserved zeus kinds and unsafe paths', () => {
    expect(normalizeZeusAgentOpenString('zeus://blueprint/morning-brief')).toBeNull()
    expect(normalizeZeusAgentOpenString('zeus://plugin/install')).toBeNull()
    expect(normalizeZeusAgentOpenString('https://example.com/x')).toBeNull()
    expect(normalizeZeusAgentOpenString('/../etc/passwd')).toBeNull()
    expect(normalizeZeusAgentOpenString('index-network')).toBeNull()
  })
})

describe('resolveZeusAgentOpenPath', () => {
  it('merges structured path + params', () => {
    expect(resolveZeusAgentOpenPath({ path: '/index-network/intent/1', params: { focus: 'true' } })).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('resolves href the same as a bare string', () => {
    expect(resolveZeusAgentOpenPath({ href: 'zeus://index-network/intent/1' })).toBe('/index-network/intent/1')
  })
})

describe('pathFromZeusAgentDeepLink', () => {
  it('builds the navigate path from a plugin-scoped deep-link payload', () => {
    expect(pathFromZeusAgentDeepLink('index-network', 'intent/1')).toBe('/index-network/intent/1')
  })

  it('builds the navigate path from zeus://open/… payloads', () => {
    expect(pathFromOpenDeepLink('index-network/intent/1')).toBe('/index-network/intent/1')
    expect(pathFromZeusAgentDeepLink('open', 'agent/42')).toBe('/agent/42')
  })

  it('ignores reserved kinds', () => {
    expect(pathFromZeusAgentDeepLink('blueprint', 'morning-brief')).toBeNull()
    expect(pathFromZeusAgentDeepLink('plugin', 'install')).toBeNull()
  })
})
