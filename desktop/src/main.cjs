const { app, BrowserWindow, Menu, Tray, ipcMain, dialog, Notification, nativeImage, globalShortcut, shell } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const os = require('node:os')
const http = require('node:http')
const https = require('node:https')
const { pipeline } = require('node:stream/promises')
const { WebSocket } = require('ws')

const { ConfigStore } = require('./config.cjs')
const { scanFolder } = require('./backup.cjs')

const APP_VERSION = '0.1.0'
let mainWindow
let tray
let store
let socket
let reconnectTimer
let clipboardTimer
let schedulerTimer
let lastClipboardText = ''
let lastRemoteText = ''
let quitting = false
const activeBackups = new Map()

function sendRenderer (event, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(`nas-link:${event}`, payload)
}

function createTrayIcon () {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
      <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#5b7cfa"/><stop offset="1" stop-color="#5ad7b7"/></linearGradient></defs>
      <rect x="4" y="4" width="56" height="56" rx="18" fill="url(#g)"/>
      <path d="M19 23h26v18H19z" fill="none" stroke="white" stroke-width="4" stroke-linejoin="round"/>
      <path d="M24 31h16M26 38h12" stroke="white" stroke-width="4" stroke-linecap="round"/>
    </svg>`
  return nativeImage.createFromDataURL(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`).resize({ width: 20, height: 20 })
}

function createWindow () {
  mainWindow = new BrowserWindow({
    width: 1240,
    height: 820,
    minWidth: 980,
    minHeight: 680,
    show: false,
    title: 'NAS Link',
    backgroundColor: '#f4f7fb',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })
  mainWindow.removeMenu()
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'))
  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.on('close', event => {
    if (!quitting) {
      event.preventDefault()
      mainWindow.hide()
    }
  })
}

function createTray () {
  tray = new Tray(createTrayIcon())
  tray.setToolTip('NAS Link')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开 NAS Link', click: () => showWindow() },
    { label: '发送当前剪贴板', click: () => sendCurrentClipboard(true) },
    { type: 'separator' },
    { label: '退出', click: () => { quitting = true; app.quit() } }
  ]))
  tray.on('click', () => showWindow())
}

function showWindow () {
  if (!mainWindow) return
  mainWindow.show()
  mainWindow.focus()
}

function authHeaders (extra = {}) {
  return { Authorization: `Bearer ${store.value.token}`, ...extra }
}

async function apiJson (endpoint, options = {}) {
  if (!store.value.token) throw new Error('请先在设置中填写连接令牌')
  const response = await fetch(`${store.value.serverUrl}${endpoint}`, {
    ...options,
    headers: authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) })
  })
  const text = await response.text()
  let data
  try { data = text ? JSON.parse(text) : null } catch { data = { detail: text } }
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `请求失败 ${response.status}`)
  return data
}

async function registerDevice () {
  if (!store.value.token) return
  await apiJson('/api/devices/register', {
    method: 'POST',
    body: JSON.stringify({
      id: store.value.deviceId,
      name: store.value.deviceName,
      platform: `${process.platform}-${process.arch}`,
      app_version: APP_VERSION
    })
  })
}

function connectRealtime () {
  clearTimeout(reconnectTimer)
  if (socket) {
    socket.removeAllListeners()
    socket.close()
  }
  if (!store.value.token) {
    sendRenderer('connection', { connected: false, message: '等待配置' })
    return
  }
  const url = new URL(store.value.serverUrl)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = '/ws'
  url.searchParams.set('device_id', store.value.deviceId)
  url.searchParams.set('token', store.value.token)
  socket = new WebSocket(url)
  socket.on('open', async () => {
    sendRenderer('connection', { connected: true, message: '已连接 NAS' })
    try { await registerDevice() } catch (error) { sendRenderer('connection', { connected: false, message: error.message }) }
  })
  socket.on('message', async raw => {
    try {
      const message = JSON.parse(String(raw))
      if (message.type === 'clipboard') {
        const item = message.item
        if (store.value.clipboardMode === 'auto' && item.source_device !== store.value.deviceId) {
          lastRemoteText = item.content
          lastClipboardText = item.content
          await Promise.resolve(require('electron').clipboard.writeText(item.content))
        }
        sendRenderer('clipboard', item)
      } else if (message.type === 'file_offer') {
        sendRenderer('file-offer', message.transfer)
        new Notification({ title: '收到文件', body: message.transfer.filename }).show()
        if (store.value.autoDownload) await downloadTransfer(message.transfer.id)
      } else if (message.type === 'library_updated') {
        sendRenderer('library-updated', message.file)
      }
    } catch {}
  })
  socket.on('close', () => {
    sendRenderer('connection', { connected: false, message: '连接已断开，正在重试' })
    reconnectTimer = setTimeout(connectRealtime, 5000)
  })
  socket.on('error', error => sendRenderer('connection', { connected: false, message: error.message }))
}

async function readClipboardText () {
  return await Promise.resolve(require('electron').clipboard.readText())
}

async function sendCurrentClipboard (notify = false) {
  const text = await readClipboardText()
  if (!text.trim()) throw new Error('当前剪贴板没有文字')
  const item = await sendClipboard(text)
  if (notify) new Notification({ title: '剪贴板已发送', body: text.slice(0, 80) }).show()
  return item
}

async function sendClipboard (text) {
  const value = String(text || '').slice(0, 200_000)
  if (!value) throw new Error('没有可发送的文字')
  lastClipboardText = value
  return await apiJson('/api/clipboard', {
    method: 'POST',
    body: JSON.stringify({ source_device: store.value.deviceId, content: value })
  })
}

async function startClipboardWatcher () {
  clearInterval(clipboardTimer)
  lastClipboardText = await readClipboardText()
  clipboardTimer = setInterval(async () => {
    if (store.value.clipboardMode !== 'auto') return
    try {
      const current = await readClipboardText()
      if (!current || current === lastClipboardText || current === lastRemoteText) return
      lastClipboardText = current
      await sendClipboard(current)
    } catch {}
  }, 800)
}

function requestStream (method, endpoint, filePath) {
  return new Promise(async (resolve, reject) => {
    try {
      const target = new URL(`${store.value.serverUrl}${endpoint}`)
      const transport = target.protocol === 'https:' ? https : http
      const stat = await fs.promises.stat(filePath)
      const request = transport.request(target, {
        method,
        headers: authHeaders({
          'Content-Type': 'application/octet-stream',
          'Content-Length': stat.size
        })
      }, response => {
        const chunks = []
        response.on('data', chunk => chunks.push(chunk))
        response.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8')
          let data
          try { data = text ? JSON.parse(text) : null } catch { data = { detail: text } }
          if (response.statusCode < 200 || response.statusCode >= 300) {
            reject(new Error(typeof data?.detail === 'string' ? data.detail : `上传失败 ${response.statusCode}`))
          } else resolve(data)
        })
      })
      request.on('error', reject)
      fs.createReadStream(filePath).pipe(request)
    } catch (error) {
      reject(error)
    }
  })
}

function uniqueDownloadPath (filename) {
  const directory = app.getPath('downloads')
  const safe = path.basename(filename).replace(/[<>:"/\\|?*\x00-\x1f]+/g, '_')
  let candidate = path.join(directory, safe)
  const extension = path.extname(safe)
  const stem = path.basename(safe, extension)
  let counter = 2
  while (fs.existsSync(candidate)) candidate = path.join(directory, `${stem} (${counter++})${extension}`)
  return candidate
}

function parseDownloadName (header, fallback) {
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header || '')
  if (utf8) return decodeURIComponent(utf8[1])
  const plain = /filename="?([^";]+)"?/i.exec(header || '')
  return plain ? plain[1] : fallback
}

function downloadEndpoint (endpoint, fallbackName) {
  return new Promise((resolve, reject) => {
    const target = new URL(`${store.value.serverUrl}${endpoint}`)
    const transport = target.protocol === 'https:' ? https : http
    const request = transport.get(target, { headers: authHeaders() }, async response => {
      if (response.statusCode < 200 || response.statusCode >= 300) {
        response.resume()
        reject(new Error(`下载失败 ${response.statusCode}`))
        return
      }
      const filename = parseDownloadName(response.headers['content-disposition'], fallbackName)
      const destination = uniqueDownloadPath(filename)
      try {
        await pipeline(response, fs.createWriteStream(destination, { flags: 'wx' }))
        resolve(destination)
      } catch (error) {
        fs.rm(destination, { force: true }, () => {})
        reject(error)
      }
    })
    request.on('error', reject)
  })
}

async function downloadTransfer (id) {
  const destination = await downloadEndpoint(`/api/transfers/${encodeURIComponent(id)}/download`, 'NAS-Link-file')
  new Notification({ title: '文件已保存', body: path.basename(destination) }).show()
  return destination
}

async function runBackup (folderPath) {
  const root = path.resolve(folderPath)
  if (activeBackups.has(root)) return await activeBackups.get(root)
  const task = (async () => {
    sendRenderer('backup-progress', { root, phase: 'scan', message: '正在扫描和计算指纹' })
    const files = await scanFolder(root, progress => sendRenderer('backup-progress', { root, ...progress }))
    const plan = await apiJson('/api/backups/plan', {
      method: 'POST',
      body: JSON.stringify({
        device_id: store.value.deviceId,
        root_name: path.basename(root),
        files: files.map(({ path: relativePath, sha256, size, mtime_ns: mtimeNs }) => ({
          path: relativePath, sha256, size, mtime_ns: mtimeNs
        }))
      })
    })
    const byHash = new Map(files.map(file => [file.sha256, file.absolute]))
    let uploaded = 0
    for (const hash of plan.missing_hashes) {
      await requestStream('PUT', `/api/backups/${encodeURIComponent(plan.snapshot_id)}/blobs/${hash}`, byHash.get(hash))
      uploaded += 1
      sendRenderer('backup-progress', {
        root, phase: 'upload', uploaded, total: plan.missing_hashes.length,
        message: `正在上传 ${uploaded}/${plan.missing_hashes.length}`
      })
    }
    const snapshot = await apiJson(`/api/backups/${encodeURIComponent(plan.snapshot_id)}/commit`, { method: 'POST' })
    store.update({ lastBackupAt: new Date().toISOString() })
    sendRenderer('config', store.value)
    sendRenderer('backup-progress', { root, phase: 'complete', snapshot, message: '备份完成' })
    return snapshot
  })().finally(() => activeBackups.delete(root))
  activeBackups.set(root, task)
  return await task
}

function startBackupScheduler () {
  clearInterval(schedulerTimer)
  schedulerTimer = setInterval(async () => {
    if (!store.value.token || !store.value.backupFolders.length) return
    const last = store.value.lastBackupAt ? Date.parse(store.value.lastBackupAt) : 0
    const interval = store.value.backupEveryHours * 60 * 60 * 1000
    if (Date.now() - last < interval) return
    for (const folder of store.value.backupFolders.filter(item => item.enabled)) {
      try { await runBackup(folder.path) } catch (error) {
        sendRenderer('backup-progress', { root: folder.path, phase: 'error', message: error.message })
      }
    }
  }, 15 * 60 * 1000)
}

function setupIpc () {
  ipcMain.handle('config:get', () => store.value)
  ipcMain.handle('config:import', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openFile'],
      filters: [{ name: 'NAS Link 连接配置', extensions: ['json'] }]
    })
    if (result.canceled) return null
    const imported = JSON.parse(await fs.promises.readFile(result.filePaths[0], 'utf8'))
    const config = store.update({
      serverUrl: imported.serverUrl,
      token: imported.token,
      deviceName: imported.deviceName || store.value.deviceName
    })
    connectRealtime()
    await registerDevice()
    return config
  })
  ipcMain.handle('config:save', async (_event, input) => {
    const previousUrl = store.value.serverUrl
    const previousToken = store.value.token
    const config = store.save(input)
    app.setLoginItemSettings({ openAtLogin: Boolean(config.launchAtLogin) })
    if (previousUrl !== config.serverUrl || previousToken !== config.token) connectRealtime()
    await registerDevice()
    return config
  })
  ipcMain.handle('dashboard:get', () => apiJson('/api/dashboard'))
  ipcMain.handle('devices:list', () => apiJson('/api/devices'))
  ipcMain.handle('clipboard:list', () => apiJson('/api/clipboard'))
  ipcMain.handle('clipboard:send-current', () => sendCurrentClipboard(false))
  ipcMain.handle('clipboard:send', (_event, text) => sendClipboard(text))
  ipcMain.handle('clipboard:apply', async (_event, text) => {
    const value = String(text || '')
    lastRemoteText = value
    lastClipboardText = value
    await Promise.resolve(require('electron').clipboard.writeText(value))
    return { ok: true }
  })
  ipcMain.handle('clipboard:clear', () => apiJson('/api/clipboard', { method: 'DELETE' }))
  ipcMain.handle('library:choose-upload', async () => {
    const result = await dialog.showOpenDialog(mainWindow, { properties: ['openFile', 'multiSelections'] })
    if (result.canceled) return []
    const uploaded = []
    for (const filePath of result.filePaths) {
      const query = new URLSearchParams({ filename: path.basename(filePath), source_device: store.value.deviceId })
      uploaded.push(await requestStream('POST', `/api/library/upload?${query}`, filePath))
    }
    return uploaded
  })
  ipcMain.handle('library:list', (_event, statusValue) => apiJson(`/api/library/files${statusValue ? `?status=${encodeURIComponent(statusValue)}` : ''}`))
  ipcMain.handle('library:search', (_event, query) => apiJson('/api/library/search', { method: 'POST', body: JSON.stringify({ query }) }))
  ipcMain.handle('library:download', async (_event, id) => downloadEndpoint(`/api/library/files/${encodeURIComponent(id)}/download`, 'NAS-Link-file'))
  ipcMain.handle('library:undo', (_event, id) => apiJson(`/api/library/files/${encodeURIComponent(id)}/undo`, { method: 'POST' }))
  ipcMain.handle('transfer:choose-send', async (_event, targetDevice) => {
    const result = await dialog.showOpenDialog(mainWindow, { properties: ['openFile', 'multiSelections'] })
    if (result.canceled) return []
    const sent = []
    for (const filePath of result.filePaths) {
      const query = new URLSearchParams({ filename: path.basename(filePath), source_device: store.value.deviceId })
      if (targetDevice) query.set('target_device', targetDevice)
      sent.push(await requestStream('POST', `/api/transfers?${query}`, filePath))
    }
    return sent
  })
  ipcMain.handle('transfer:list', () => apiJson(`/api/transfers?device_id=${encodeURIComponent(store.value.deviceId)}`))
  ipcMain.handle('transfer:download', (_event, id) => downloadTransfer(id))
  ipcMain.handle('backup:choose-folder', async () => {
    const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory'] })
    if (result.canceled) return null
    const folder = { path: result.filePaths[0], name: path.basename(result.filePaths[0]), enabled: true }
    const duplicate = store.value.backupFolders.some(item => path.resolve(item.path) === path.resolve(folder.path))
    if (!duplicate) store.update({ backupFolders: [...store.value.backupFolders, folder] })
    sendRenderer('config', store.value)
    return folder
  })
  ipcMain.handle('backup:run', (_event, folderPath) => runBackup(folderPath))
  ipcMain.handle('backup:list', () => apiJson('/api/backups'))
  ipcMain.handle('backup:manifest', (_event, snapshotId) => apiJson(`/api/backups/${encodeURIComponent(snapshotId)}/manifest`))
  ipcMain.handle('backup:restore', (_event, snapshotId, relativePath) => {
    const query = new URLSearchParams({ path: relativePath })
    return downloadEndpoint(`/api/backups/${encodeURIComponent(snapshotId)}/restore?${query}`, path.basename(relativePath))
  })
  ipcMain.handle('shell:show-item', (_event, filePath) => shell.showItemInFolder(filePath))
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => showWindow())
  app.whenReady().then(async () => {
    store = new ConfigStore(path.join(app.getPath('userData'), 'config.json'))
    setupIpc()
    createWindow()
    createTray()
    await startClipboardWatcher()
    connectRealtime()
    startBackupScheduler()
    globalShortcut.register('CommandOrControl+Alt+C', () => sendCurrentClipboard(true).catch(error => {
      new Notification({ title: '剪贴板发送失败', body: error.message }).show()
    }))
  })
}

app.on('before-quit', () => { quitting = true })
app.on('will-quit', () => globalShortcut.unregisterAll())
app.on('activate', () => showWindow())
app.on('window-all-closed', () => {})
