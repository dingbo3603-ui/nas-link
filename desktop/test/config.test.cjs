const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { ConfigStore, configForRenderer, mergeSettingsInput, normalizeServerUrl, sanitizeConfig } = require('../src/config.cjs')

test('normalizes and persists desktop configuration without losing device identity', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nas-link-config-'))
  const file = path.join(root, 'config.json')
  const store = new ConfigStore(file)
  const firstId = store.value.deviceId
  store.update({ serverUrl: 'http://192.168.31.35:8766/', token: 'abc', clipboardMode: 'auto' })
  const reloaded = new ConfigStore(file)
  assert.equal(reloaded.value.serverUrl, 'http://192.168.31.35:8766')
  assert.equal(reloaded.value.deviceId, firstId)
  assert.equal(reloaded.value.clipboardMode, 'auto')
})

test('rejects non-http server URLs and clamps backup interval', () => {
  assert.throws(() => normalizeServerUrl('file:///tmp/nas'))
  assert.equal(sanitizeConfig({ backupEveryHours: 999 }).backupEveryHours, 168)
})

test('keeps an existing token when the settings form leaves it blank', () => {
  const merged = mergeSettingsInput(
    sanitizeConfig({ token: 'saved-secret', deviceName: 'Windows' }),
    { token: '', deviceName: 'Office Windows', tokenConfigured: true }
  )

  assert.equal(merged.token, 'saved-secret')
  assert.equal(merged.deviceName, 'Office Windows')
  assert.equal(Object.hasOwn(merged, 'tokenConfigured'), false)
})

test('does not expose a saved token to the renderer', () => {
  const publicConfig = configForRenderer(sanitizeConfig({ token: 'saved-secret' }))
  assert.equal(publicConfig.token, '')
  assert.equal(publicConfig.tokenConfigured, true)
})

test('does not overwrite an existing config when a startup read fails', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nas-link-config-invalid-'))
  const file = path.join(root, 'config.json')
  fs.writeFileSync(file, '{invalid-json', 'utf8')

  const store = new ConfigStore(file)

  assert.equal(store.value.token, '')
  assert.equal(fs.readFileSync(file, 'utf8'), '{invalid-json')
})
