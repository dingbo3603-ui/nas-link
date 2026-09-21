const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { ConfigStore, normalizeServerUrl, sanitizeConfig } = require('../src/config.cjs')

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
