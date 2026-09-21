const { app, BrowserWindow, ipcMain } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const output = path.join(__dirname, '..', 'dist')
const config = {
  serverUrl: 'http://192.168.31.35:8766',
  token: 'visual-test-token',
  deviceId: 'qa-windows',
  deviceName: '办公室 Windows',
  clipboardMode: 'manual',
  autoDownload: false,
  launchAtLogin: false,
  backupEveryHours: 6,
  lastBackupAt: '2026-09-21T03:00:00Z',
  backupFolders: [
    { path: 'C:\\Users\\Administrator\\Documents', name: '工作文档', enabled: true },
    { path: 'D:\\设计资料', name: '设计资料', enabled: true }
  ]
}

const samples = {
  dashboard: {
    devices: 3,
    registered_devices: 3,
    files: { organized: 1286, needs_review: 17, duplicate: 4 },
    backup_snapshots: { count: 42, bytes: 38654705664 },
    storage: { total: 8589934592000, used: 3221225472000, free: 5368709120000 },
    deepseek_configured: true
  },
  devices: [
    { id: 'qa-windows', name: '办公室 Windows', platform: 'win32-x64', online: true, last_seen: new Date().toISOString() },
    { id: 'design-windows', name: '设计 Windows', platform: 'win32-x64', online: true, last_seen: new Date().toISOString() },
    { id: 'macbook', name: 'MacBook', platform: 'darwin-arm64', online: true, last_seen: new Date().toISOString() }
  ],
  transfers: [
    { id: 't1', filename: '德国站广告报表.xlsx', size: 184320, created_at: new Date().toISOString() },
    { id: 't2', filename: '旗帜订单图片.zip', size: 8345728, created_at: new Date().toISOString() }
  ],
  backups: [
    { id: 's1', root_name: '工作文档', status: 'complete', total_files: 830, total_bytes: 2456789012, completed_at: new Date().toISOString() },
    { id: 's2', root_name: '设计资料', status: 'complete', total_files: 192, total_bytes: 12456789012, completed_at: '2026-09-20T12:00:00Z' }
  ],
  library: [
    { id: 'f1', original_name: '德国站广告报表.xlsx', extension: '.xlsx', relative_path: '电商运营/广告报表/2026/09/德国站广告报表.xlsx', category: '电商运营', subcategory: '广告报表', summary: '德国站九月广告表现与搜索词数据', status: 'organized' },
    { id: 'f2', original_name: '供应商报价单.pdf', extension: '.pdf', relative_path: '商务资料/报价单/2026/09/供应商报价单.pdf', category: '商务资料', subcategory: '报价单', summary: '供应商最新产品报价', status: 'organized' }
  ]
}

function registerMocks () {
  const handlers = {
    'config:get': () => config,
    'connection:get': () => ({ connected: true, phase: 'connected', message: '实时通道正常', serverUrl: config.serverUrl, connectedAt: new Date().toISOString(), lastHeartbeatAt: new Date().toISOString(), retryAt: null }),
    'config:save': (_event, next) => Object.assign(config, next),
    'dashboard:get': () => samples.dashboard,
    'devices:list': () => samples.devices,
    'clipboard:list': () => [],
    'transfer:list': () => samples.transfers,
    'backup:list': () => samples.backups,
    'library:list': () => samples.library,
    'clipboard:send-current': () => ({}),
    'library:choose-upload': () => ({ items: [], failed: [] }),
    'library:upload-paths': () => ({ items: [], failed: [] }),
    'backup:choose-folder': () => null,
    'shell:show-item': () => null
  }
  for (const [channel, handler] of Object.entries(handlers)) ipcMain.handle(channel, handler)
}

async function capture (window, name) {
  const image = await window.webContents.capturePage()
  fs.writeFileSync(path.join(output, name), image.toPNG())
}

app.whenReady().then(async () => {
  fs.mkdirSync(output, { recursive: true })
  registerMocks()
  const window = new BrowserWindow({
    width: 1240,
    height: 820,
    show: true,
    backgroundColor: '#f3f6fb',
    webPreferences: {
      preload: path.join(__dirname, '..', 'src', 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false
    }
  })
  await window.loadFile(path.join(__dirname, '..', 'src', 'renderer', 'index.html'))
  await new Promise(resolve => setTimeout(resolve, 1000))
  await capture(window, 'qa-overview.png')
  await window.webContents.executeJavaScript("document.querySelector('[data-page=library]').click()")
  await new Promise(resolve => setTimeout(resolve, 600))
  await capture(window, 'qa-library.png')
  await window.webContents.executeJavaScript("document.querySelector('[data-page=backup]').click()")
  await new Promise(resolve => setTimeout(resolve, 600))
  await capture(window, 'qa-backup.png')
  await window.webContents.executeJavaScript("document.querySelector('[data-page=assistant]').click()")
  await new Promise(resolve => setTimeout(resolve, 600))
  await capture(window, 'qa-assistant.png')
  window.destroy()
  app.quit()
})
