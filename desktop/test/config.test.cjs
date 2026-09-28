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
  store.update({ serverUrl: 'http://192.168.31.35:8766/', clipboardMode: 'auto' })
  const reloaded = new ConfigStore(file)
  assert.equal(reloaded.value.serverUrl, 'http://192.168.31.35:8766')
  assert.equal(reloaded.value.deviceId, firstId)
  assert.equal(reloaded.value.clipboardMode, 'auto')
})

test('rejects non-http server URLs and clamps backup interval', () => {
  assert.throws(() => normalizeServerUrl('file:///tmp/nas'))
  assert.equal(sanitizeConfig({ backupEveryHours: 999 }).backupEveryHours, 168)
})

test('does not overwrite an existing config when a startup read fails', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nas-link-config-invalid-'))
  const file = path.join(root, 'config.json')
  fs.writeFileSync(file, '{invalid-json', 'utf8')

  const store = new ConfigStore(file)

  assert.equal(fs.readFileSync(file, 'utf8'), '{invalid-json')
})

test('removes legacy connection credentials while keeping desktop preferences', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nas-link-config-migrate-'))
  const file = path.join(root, 'config.json')
  fs.writeFileSync(file, JSON.stringify({ token: 'legacy-secret', deviceName: 'Office Windows', clipboardMode: 'auto' }), 'utf8')

  const store = new ConfigStore(file)
  const saved = JSON.parse(fs.readFileSync(file, 'utf8'))

  assert.equal(store.value.deviceName, 'Office Windows')
  assert.equal(store.value.clipboardMode, 'auto')
  assert.equal(Object.hasOwn(saved, 'token'), false)
})
