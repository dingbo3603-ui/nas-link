const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const crypto = require('node:crypto')

const DEFAULTS = Object.freeze({
  serverUrl: 'http://192.168.31.35:8766',
  token: '',
  deviceId: '',
  deviceName: '',
  clipboardMode: 'manual',
  autoDownload: false,
  launchAtLogin: false,
  backupFolders: [],
  backupEveryHours: 6,
  lastBackupAt: null
})

function normalizeServerUrl (value) {
  const raw = String(value || '').trim().replace(/\/+$/, '')
  if (!/^https?:\/\//i.test(raw)) throw new Error('服务器地址必须以 http:// 或 https:// 开头')
  return raw
}

function sanitizeConfig (input = {}) {
  const config = { ...DEFAULTS, ...input }
  config.serverUrl = normalizeServerUrl(config.serverUrl)
  config.token = String(config.token || '').trim()
  config.deviceId = String(config.deviceId || crypto.randomUUID())
  config.deviceName = String(config.deviceName || os.hostname()).trim().slice(0, 100)
  config.clipboardMode = ['manual', 'auto', 'off'].includes(config.clipboardMode) ? config.clipboardMode : 'manual'
  config.autoDownload = Boolean(config.autoDownload)
  config.launchAtLogin = Boolean(config.launchAtLogin)
  config.backupEveryHours = Math.max(1, Math.min(168, Number(config.backupEveryHours) || 6))
  config.backupFolders = Array.isArray(config.backupFolders)
    ? config.backupFolders.filter(item => item && typeof item.path === 'string').map(item => ({
        path: path.resolve(item.path),
        name: String(item.name || path.basename(item.path)).slice(0, 200),
        enabled: item.enabled !== false
      }))
    : []
  return config
}

class ConfigStore {
  constructor (filePath) {
    this.filePath = filePath
    this.value = this.load()
  }

  load () {
    try {
      return sanitizeConfig(JSON.parse(fs.readFileSync(this.filePath, 'utf8')))
    } catch {
      const config = sanitizeConfig()
      this.save(config)
      return config
    }
  }

  save (next) {
    const config = sanitizeConfig(next)
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true })
    const temporary = `${this.filePath}.tmp`
    fs.writeFileSync(temporary, JSON.stringify(config, null, 2), { encoding: 'utf8', mode: 0o600 })
    fs.renameSync(temporary, this.filePath)
    this.value = config
    return config
  }

  update (patch) {
    return this.save({ ...this.value, ...patch })
  }
}

module.exports = { ConfigStore, DEFAULTS, normalizeServerUrl, sanitizeConfig }
