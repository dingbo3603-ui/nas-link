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
  const source = { ...DEFAULTS, ...input }
  const config = { ...DEFAULTS }
  config.serverUrl = normalizeServerUrl(source.serverUrl)
  config.token = String(source.token || '').trim()
  config.deviceId = String(source.deviceId || crypto.randomUUID())
  config.deviceName = String(source.deviceName || os.hostname()).trim().slice(0, 100)
  config.clipboardMode = ['manual', 'auto', 'off'].includes(source.clipboardMode) ? source.clipboardMode : 'manual'
  config.autoDownload = Boolean(source.autoDownload)
  config.launchAtLogin = Boolean(source.launchAtLogin)
  config.backupEveryHours = Math.max(1, Math.min(168, Number(source.backupEveryHours) || 6))
  config.backupFolders = Array.isArray(source.backupFolders)
    ? source.backupFolders.filter(item => item && typeof item.path === 'string').map(item => ({
        path: path.resolve(item.path),
        name: String(item.name || path.basename(item.path)).slice(0, 200),
        enabled: item.enabled !== false
      }))
    : []
  config.lastBackupAt = source.lastBackupAt ? String(source.lastBackupAt) : null
  return config
}

function configForRenderer (config) {
  const { token, ...safe } = sanitizeConfig(config)
  return { ...safe, token: '', tokenConfigured: Boolean(token) }
}

function mergeSettingsInput (current, input = {}) {
  const replacement = String(input.token || '').trim()
  return sanitizeConfig({ ...current, ...input, token: replacement || current.token })
}

class ConfigStore {
  constructor (filePath) {
    this.filePath = filePath
    this.value = this.load()
  }

  load () {
    try {
      return sanitizeConfig(JSON.parse(fs.readFileSync(this.filePath, 'utf8')))
    } catch (error) {
      const config = sanitizeConfig()
      if (error?.code === 'ENOENT') this.save(config)
      return config
    }
  }

  reload () {
    const config = sanitizeConfig(JSON.parse(fs.readFileSync(this.filePath, 'utf8')))
    this.value = config
    return config
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

module.exports = { ConfigStore, DEFAULTS, configForRenderer, mergeSettingsInput, normalizeServerUrl, sanitizeConfig }
