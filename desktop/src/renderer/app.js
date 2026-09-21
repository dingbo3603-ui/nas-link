const state = {
  page: 'overview',
  config: null,
  connection: null,
  dashboard: null,
  devices: [],
  clipboard: [],
  library: [],
  libraryStatus: '',
  transfers: [],
  backups: [],
  restore: null,
  search: null
}

const pageMeta = {
  overview: ['总览', '所有设备、文件和备份，一眼看清。'],
  clipboard: ['共享剪贴板', '在自己的设备之间快速复制文字。'],
  library: ['智能资料库', '先安全入库，再自动归类和索引。'],
  backup: ['备份中心', '每台电脑独立快照，保留历史版本。'],
  assistant: ['DeepSeek 找文件', '说出你记得的内容，找回真实文件。'],
  settings: ['设置', '连接、安全和自动化偏好。']
}

const $ = selector => document.querySelector(selector)
const $$ = selector => [...document.querySelectorAll(selector)]

function escapeHtml (value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function formatBytes (bytes) {
  const value = Number(bytes || 0)
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let number = value / 1024
  let index = 0
  while (number >= 1024 && index < units.length - 1) { number /= 1024; index += 1 }
  return `${number >= 10 ? number.toFixed(0) : number.toFixed(1)} ${units[index]}`
}

function formatDate (value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

function toast (message, isError = false, duration = 2800) {
  const element = $('#toast')
  element.textContent = message
  element.classList.toggle('error', isError)
  element.classList.add('show')
  clearTimeout(toast.timer)
  toast.timer = setTimeout(() => element.classList.remove('show'), duration)
}

async function run (work, successMessage) {
  try {
    const result = await work()
    if (successMessage) toast(successMessage)
    return result
  } catch (error) {
    toast(error.message || String(error), true)
    throw error
  }
}

function showPage (page) {
  state.page = page
  $$('.page').forEach(element => element.classList.toggle('active', element.id === `page-${page}`))
  $$('.nav-item').forEach(element => element.classList.toggle('active', element.dataset.page === page))
  $('#page-title').textContent = pageMeta[page][0]
  $('#page-subtitle').textContent = pageMeta[page][1]
  if (page === 'clipboard') refreshClipboard()
  if (page === 'library') refreshLibrary()
  if (page === 'backup') refreshBackups()
}

function renderConnection (payload) {
  state.connection = payload || state.connection || {}
  const connection = state.connection
  const dot = $('#connection-dot')
  dot.classList.toggle('connected', Boolean(connection.connected))
  dot.classList.toggle('connecting', ['starting', 'connecting', 'retrying'].includes(connection.phase))
  const titles = { starting: '正在启动', connecting: '正在连接', retrying: '正在重连', waiting: '等待配置', stale: '连接超时', error: 'NAS 未连接' }
  $('#connection-title').textContent = connection.connected ? 'NAS 已连接' : (titles[connection.phase] || 'NAS 未连接')
  if (connection.connected && connection.lastHeartbeatAt) {
    $('#connection-detail').textContent = `实时通道正常 · ${new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(connection.lastHeartbeatAt))}`
  } else {
    $('#connection-detail').textContent = connection.message || connection.serverUrl || state.config?.serverUrl || '等待配置'
  }
}

function renderSetup () {
  $('#setup-banner').classList.toggle('hidden', Boolean(state.config?.token))
}

function renderDashboard () {
  const data = state.dashboard || {}
  const files = data.files || {}
  const backup = data.backup_snapshots || {}
  const storage = data.storage || {}
  const items = [
    ['在线设备', String(data.devices || 0), `已登记 ${data.registered_devices || 0} 台`, '●'],
    ['资料库', String((files.organized || 0) + (files.needs_review || 0)), `待确认 ${files.needs_review || 0} 项`, '▣'],
    ['备份快照', String(backup.count || 0), formatBytes(backup.bytes), '↻'],
    ['NAS 可用空间', formatBytes(storage.free), `总计 ${formatBytes(storage.total)}`, '◫']
  ]
  $('#metric-grid').innerHTML = items.map(item => `
    <div class="metric"><div class="metric-head"><span>${escapeHtml(item[0])}</span><span class="metric-icon">${item[3]}</span></div>
      <strong>${escapeHtml(item[1])}</strong><small>${escapeHtml(item[2])}</small></div>`).join('')
}

function renderDevices () {
  const container = $('#device-grid')
  if (!state.devices.length) {
    container.className = 'device-grid empty-state'
    container.textContent = '还没有登记设备'
    return
  }
  container.className = 'device-grid'
  container.innerHTML = state.devices.map(device => `
    <div class="device-card">
      <div class="device-top"><span class="device-avatar">${escapeHtml(device.platform?.startsWith('darwin') ? 'Mac' : 'Win')}</span><span class="online-pill ${device.online ? 'yes' : ''}"></span></div>
      <strong title="${escapeHtml(device.name)}">${escapeHtml(device.name)}</strong>
      <small>${device.online ? '在线' : `上次 ${formatDate(device.last_seen)}`}</small>
      <button data-send-device="${escapeHtml(device.id)}" ${device.id === state.config?.deviceId ? 'disabled' : ''}>发送文件</button>
    </div>`).join('')
}

function renderTransfers () {
  const container = $('#transfer-list')
  const items = state.transfers.slice(0, 4)
  container.innerHTML = items.map(item => `
    <div class="mini-item"><span class="file-glyph">${escapeHtml((item.filename.split('.').pop() || 'FILE').slice(0, 4).toUpperCase())}</span>
      <div><strong>${escapeHtml(item.filename)}</strong><small>${formatBytes(item.size)} · ${formatDate(item.created_at)}</small></div>
      <button data-download-transfer="${escapeHtml(item.id)}">下载</button></div>`).join('')
}

function renderClipboardMode () {
  $$('#clipboard-mode button').forEach(button => button.classList.toggle('active', button.dataset.mode === state.config?.clipboardMode))
}

function renderClipboard () {
  renderClipboardMode()
  const container = $('#clipboard-history')
  if (!state.clipboard.length) {
    container.className = 'history-list empty-state'
    container.textContent = '还没有共享记录'
    return
  }
  container.className = 'history-list'
  container.innerHTML = state.clipboard.map(item => `
    <button class="history-item" data-copy-history="${escapeHtml(item.id)}">
      <span class="history-meta"><span>${escapeHtml(deviceName(item.source_device))}</span><span>${formatDate(item.created_at)}</span></span>
      <p>${escapeHtml(item.content)}</p>
    </button>`).join('')
}

function deviceName (id) {
  return state.devices.find(device => device.id === id)?.name || '未知设备'
}

function statusLabel (status) {
  return ({ organized: '已归档', needs_review: '待确认', duplicate: '重复', inbox: '处理中', error: '异常' })[status] || status
}

function renderLibrary () {
  const container = $('#library-list')
  if (!state.library.length) {
    container.className = 'file-list empty-state'
    container.textContent = '这里还没有文件'
    return
  }
  container.className = 'file-list'
  container.innerHTML = state.library.map(file => `
    <div class="file-row">
      <div class="file-main"><span class="file-glyph">${escapeHtml((file.extension || 'FILE').replace('.', '').slice(0, 4).toUpperCase())}</span><div><strong title="${escapeHtml(file.original_name)}">${escapeHtml(file.original_name)}</strong><small title="${escapeHtml(file.relative_path)}">${escapeHtml(file.relative_path)}</small></div></div>
      <div><span class="tag">${escapeHtml(file.category || '未分类')} / ${escapeHtml(file.subcategory || '—')}</span></div>
      <div class="file-summary"><span class="tag" title="${escapeHtml(file.summary || '')}">${escapeHtml(file.summary || '暂无摘要')}</span></div>
      <div><span class="status ${escapeHtml(file.status)}">${escapeHtml(statusLabel(file.status))}</span></div>
      <div class="file-actions"><button data-download-library="${escapeHtml(file.id)}">下载</button>${file.status === 'organized' ? `<button data-undo-library="${escapeHtml(file.id)}">撤销归档</button>` : ''}</div>
    </div>`).join('')
}

function renderBackupFolders () {
  const container = $('#backup-folders')
  const folders = state.config?.backupFolders || []
  if (!folders.length) {
    container.className = 'backup-folders empty-state'
    container.textContent = '还没有选择备份文件夹'
    return
  }
  container.className = 'backup-folders'
  container.innerHTML = folders.map((folder, index) => `
    <div class="backup-folder"><span class="folder-icon">▰</span><div><strong>${escapeHtml(folder.name)}</strong><small title="${escapeHtml(folder.path)}">${escapeHtml(folder.path)}</small></div>
      <div class="row"><button data-run-backup="${escapeHtml(folder.path)}">立即备份</button><button class="remove" data-remove-backup="${index}">移除</button></div></div>`).join('')
}

function renderBackups () {
  renderBackupFolders()
  const container = $('#snapshot-list')
  if (!state.backups.length) {
    container.className = 'mini-list empty-state'
    container.textContent = '暂无快照'
    return
  }
  container.className = 'mini-list'
  container.innerHTML = state.backups.slice(0, 12).map(snapshot => `
    <div class="mini-item"><span class="file-glyph">↻</span><div><strong>${escapeHtml(snapshot.root_name)}</strong>
      <small>${snapshot.total_files} 个文件 · ${formatBytes(snapshot.total_bytes)} · ${formatDate(snapshot.completed_at || snapshot.created_at)}</small></div><button data-view-snapshot="${escapeHtml(snapshot.id)}">查看</button></div>`).join('')
  renderRestore()
}

function renderRestore () {
  const container = $('#restore-browser')
  if (!state.restore) { container.classList.add('hidden'); return }
  container.classList.remove('hidden')
  container.innerHTML = `<h4>${escapeHtml(state.restore.root_name)} · 选择要恢复的文件</h4><div class="restore-list">${(state.restore.entries || []).map(file => `
    <div class="restore-file"><span title="${escapeHtml(file.relative_path)}">${escapeHtml(file.relative_path)}</span><small>${formatBytes(file.size)}</small><button data-restore-file="${escapeHtml(file.relative_path)}" data-snapshot-id="${escapeHtml(state.restore.id)}">恢复</button></div>`).join('')}</div>`
}

function renderSettings () {
  const config = state.config
  if (!config) return
  $('#setting-server').value = config.serverUrl
  $('#setting-token').value = config.token
  $('#setting-device').value = config.deviceName
  $('#setting-clipboard').value = config.clipboardMode
  $('#setting-interval').value = String(config.backupEveryHours)
  $('#setting-download').checked = config.autoDownload
  $('#setting-startup').checked = config.launchAtLogin
  $('#settings-note').textContent = config.lastBackupAt ? `最近备份：${formatDate(config.lastBackupAt)}` : '尚未完成备份'
}

function renderSearch () {
  const container = $('#assistant-result')
  if (!state.search) { container.classList.add('hidden'); return }
  container.classList.remove('hidden')
  container.innerHTML = `<div class="answer-bubble">${escapeHtml(state.search.answer)}</div><div class="result-files">${(state.search.files || []).map(file => `
    <div class="result-file"><span class="file-glyph">${escapeHtml((file.extension || 'FILE').replace('.', '').slice(0, 4).toUpperCase())}</span><div><strong>${escapeHtml(file.original_name)}</strong><small>${escapeHtml(file.relative_path)}</small></div><button data-download-library="${escapeHtml(file.id)}">下载</button></div>`).join('')}</div>`
}

async function refreshClipboard () {
  if (!state.config?.token) return
  state.clipboard = await run(() => window.nasLink.getClipboard()).catch(() => state.clipboard)
  renderClipboard()
}

async function refreshLibrary () {
  if (!state.config?.token) return
  state.library = await run(() => window.nasLink.listLibrary(state.libraryStatus)).catch(() => state.library)
  renderLibrary()
}

async function refreshBackups () {
  if (!state.config?.token) return
  state.backups = await run(() => window.nasLink.listBackups()).catch(() => state.backups)
  renderBackups()
}

async function refreshOverview () {
  if (!state.config?.token) return
  const settled = await Promise.allSettled([
    window.nasLink.getDashboard(), window.nasLink.getDevices(), window.nasLink.listTransfers()
  ])
  if (settled[0].status === 'fulfilled') state.dashboard = settled[0].value
  if (settled[1].status === 'fulfilled') state.devices = settled[1].value
  if (settled[2].status === 'fulfilled') state.transfers = settled[2].value
  renderDashboard(); renderDevices(); renderTransfers()
}

async function loadAll () {
  const [config, connection] = await Promise.all([window.nasLink.getConfig(), window.nasLink.getConnectionState()])
  state.config = config
  renderConnection(connection)
  renderSetup(); renderSettings(); renderClipboardMode(); renderBackupFolders()
  if (!state.config.token) { showPage('settings'); return }
  await refreshOverview()
}

async function uploadLibrary () {
  const result = await run(() => window.nasLink.chooseAndUploadLibrary())
  await finishLibraryUpload(result)
}

async function finishLibraryUpload (result) {
  const uploaded = result?.items?.length || 0
  const failures = result?.failed || []
  const failed = failures.length
  const errorBox = $('#library-upload-errors')
  if (uploaded) { await refreshLibrary(); await refreshOverview() }
  errorBox.classList.toggle('hidden', !failed)
  errorBox.innerHTML = failed
    ? `<strong>${escapeHtml(`有 ${failed} 个文件未保存`)}</strong><ul>${failures.slice(0, 5).map(item => `<li>${escapeHtml(item.name)}：${escapeHtml(item.reason)}</li>`).join('')}</ul>${failed > 5 ? `<div>另有 ${failed - 5} 个文件未显示</div>` : ''}`
    : ''
  if (failed) toast(`已保存 ${uploaded} 个，${failed} 个未成功：${failures[0].reason}`, true, 7000)
  else if (uploaded) toast(`已保存 ${uploaded} 个文件到智能资料库`)
}

async function uploadDroppedFiles (files) {
  const paths = []
  const pathFailures = []
  for (const file of files) {
    try {
      const filePath = window.nasLink.getPathForFile(file)
      if (filePath) paths.push(filePath)
      else pathFailures.push({ name: file.name || '未知文件', reason: '无法取得本地路径；请先把文件保存到本地磁盘后再拖入' })
    } catch {
      pathFailures.push({ name: file.name || '未知文件', reason: '无法取得本地路径；请先把文件保存到本地磁盘后再拖入' })
    }
  }
  if (pathFailures.length) await finishLibraryUpload({ items: [], failed: pathFailures })
  if (!paths.length) {
    if (!pathFailures.length) toast('没有读取到可上传的文件', true)
    return
  }
  const dropzone = $('#library-dropzone')
  dropzone.classList.add('is-uploading')
  dropzone.setAttribute('aria-busy', 'true')
  $('#library-drop-status').textContent = '正在扫描文件夹…'
  try {
    const result = await run(() => window.nasLink.uploadLibraryPaths(paths))
    if (pathFailures.length) result.failed = [...pathFailures, ...(result.failed || [])]
    await finishLibraryUpload(result)
  } finally {
    dropzone.classList.remove('is-uploading')
    dropzone.removeAttribute('aria-busy')
  }
}

async function performBackup (folderPath) {
  await run(() => window.nasLink.runBackup(folderPath), '备份快照已完成')
  await refreshBackups(); await refreshOverview()
}

document.addEventListener('click', async event => {
  const button = event.target.closest('button')
  if (!button) return
  if (button.dataset.page) showPage(button.dataset.page)
  if (button.dataset.go) showPage(button.dataset.go)
  if (button.dataset.action === 'send-file-nas') {
    await run(() => window.nasLink.chooseAndSendFile(null), '文件已交给 NAS 中转')
    await refreshOverview()
  }
  if (button.dataset.sendDevice) {
    await run(() => window.nasLink.chooseAndSendFile(button.dataset.sendDevice), '文件已发送')
    await refreshOverview()
  }
  if (button.dataset.downloadTransfer) {
    const saved = await run(() => window.nasLink.downloadTransfer(button.dataset.downloadTransfer), '文件已保存到下载目录')
    if (saved) await window.nasLink.openLocalPath(saved)
  }
  if (button.dataset.copyHistory) {
    const item = state.clipboard.find(candidate => candidate.id === button.dataset.copyHistory)
    if (item) await run(() => window.nasLink.applyClipboard(item.content), '已复制到本机剪贴板')
  }
  if (button.dataset.status !== undefined) {
    state.libraryStatus = button.dataset.status
    $$('.filter').forEach(item => item.classList.toggle('active', item === button))
    await refreshLibrary()
  }
  if (button.dataset.downloadLibrary) {
    const saved = await run(() => window.nasLink.downloadLibraryFile(button.dataset.downloadLibrary), '文件已保存到下载目录')
    if (saved) await window.nasLink.openLocalPath(saved)
  }
  if (button.dataset.undoLibrary) {
    await run(() => window.nasLink.undoLibraryFile(button.dataset.undoLibrary), '已移回待确认区')
    await refreshLibrary()
  }
  if (button.dataset.runBackup) await performBackup(button.dataset.runBackup)
  if (button.dataset.viewSnapshot) {
    state.restore = await run(() => window.nasLink.getBackupManifest(button.dataset.viewSnapshot))
    renderRestore()
  }
  if (button.dataset.restoreFile) {
    const saved = await run(() => window.nasLink.restoreBackupFile(button.dataset.snapshotId, button.dataset.restoreFile), '文件已恢复到下载目录')
    if (saved) await window.nasLink.openLocalPath(saved)
  }
  if (button.dataset.removeBackup !== undefined) {
    const folders = state.config.backupFolders.filter((_item, index) => index !== Number(button.dataset.removeBackup))
    state.config = await run(() => window.nasLink.saveConfig({ ...state.config, backupFolders: folders }), '备份任务已移除')
    renderBackups()
  }
  if (button.dataset.mode) {
    state.config = await run(() => window.nasLink.saveConfig({ ...state.config, clipboardMode: button.dataset.mode }), '剪贴板模式已更新')
    renderClipboardMode(); renderSettings()
  }
  if (button.parentElement?.classList.contains('suggestions')) {
    $('#assistant-query').value = button.textContent
    $('#assistant-form').requestSubmit()
  }
})

$$('.nav-item').forEach(button => button.addEventListener('click', () => button.dataset.page && showPage(button.dataset.page)))
$('#quick-upload').addEventListener('click', uploadLibrary)
$('#library-upload').addEventListener('click', uploadLibrary)
$('#library-dropzone').addEventListener('click', uploadLibrary)
let libraryDragDepth = 0
$('#library-dropzone').addEventListener('dragenter', event => {
  event.preventDefault(); libraryDragDepth += 1; event.currentTarget.classList.add('is-dragover')
})
$('#library-dropzone').addEventListener('dragover', event => {
  event.preventDefault(); event.dataTransfer.dropEffect = 'copy'
})
$('#library-dropzone').addEventListener('dragleave', event => {
  event.preventDefault(); libraryDragDepth = Math.max(0, libraryDragDepth - 1)
  if (!libraryDragDepth) event.currentTarget.classList.remove('is-dragover')
})
$('#library-dropzone').addEventListener('drop', async event => {
  event.preventDefault(); libraryDragDepth = 0; event.currentTarget.classList.remove('is-dragover')
  await uploadDroppedFiles([...event.dataTransfer.files])
})
document.addEventListener('dragover', event => event.preventDefault())
document.addEventListener('drop', event => event.preventDefault())
$('#quick-copy').addEventListener('click', () => run(() => window.nasLink.sendCurrentClipboard(), '当前剪贴板已发送'))
$('#send-clipboard').addEventListener('click', async () => {
  const text = $('#clipboard-compose').value
  await run(() => window.nasLink.sendClipboard(text), '文字已发送到所有设备')
  $('#clipboard-compose').value = ''; $('#clipboard-count').textContent = '0 / 200000'; await refreshClipboard()
})
$('#clipboard-compose').addEventListener('input', event => { $('#clipboard-count').textContent = `${event.target.value.length} / 200000` })
$('#clear-clipboard').addEventListener('click', async () => { await run(() => window.nasLink.clearClipboard(), '剪贴板历史已清空'); await refreshClipboard() })
$('#add-backup-folder').addEventListener('click', async () => { await run(() => window.nasLink.chooseBackupFolder(), '已添加备份文件夹'); state.config = await window.nasLink.getConfig(); renderBackups() })
$('#run-all-backups').addEventListener('click', async () => {
  for (const folder of state.config.backupFolders.filter(item => item.enabled)) await performBackup(folder.path)
})

$('#assistant-form').addEventListener('submit', async event => {
  event.preventDefault()
  const query = $('#assistant-query').value.trim()
  if (!query) return
  $('#assistant-result').classList.remove('hidden')
  $('#assistant-result').innerHTML = '<div class="answer-bubble">正在检索资料库并核对真实路径……</div>'
  state.search = await run(() => window.nasLink.searchLibrary(query)).catch(() => null)
  renderSearch()
})

$('#settings-form').addEventListener('submit', async event => {
  event.preventDefault()
  const next = {
    ...state.config,
    serverUrl: $('#setting-server').value,
    token: $('#setting-token').value,
    deviceName: $('#setting-device').value,
    clipboardMode: $('#setting-clipboard').value,
    backupEveryHours: Number($('#setting-interval').value),
    autoDownload: $('#setting-download').checked,
    launchAtLogin: $('#setting-startup').checked
  }
  state.config = await run(() => window.nasLink.saveConfig(next), '设置已保存')
  renderSetup(); renderSettings(); renderClipboardMode(); await refreshOverview(); showPage('overview')
})
$('#import-config').addEventListener('click', async () => {
  const imported = await run(() => window.nasLink.importConfig(), '连接配置已导入')
  if (!imported) return
  state.config = imported
  renderSetup(); renderSettings(); renderClipboardMode(); await refreshOverview(); showPage('overview')
})

window.nasLink.on('connection', renderConnection)
window.nasLink.on('clipboard', async () => { if (state.page === 'clipboard') await refreshClipboard() })
window.nasLink.on('file-offer', async () => { toast('收到一个新文件'); await refreshOverview() })
window.nasLink.on('library-updated', async () => { if (state.page === 'library') await refreshLibrary(); await refreshOverview() })
window.nasLink.on('library-upload-progress', progress => {
  const status = $('#library-drop-status')
  if (progress.phase === 'upload') status.textContent = progress.message
  if (progress.phase === 'complete') status.textContent = progress.message
})
window.nasLink.on('config', config => { state.config = config; renderSettings(); renderBackups() })
window.nasLink.on('backup-progress', progress => {
  const banner = $('#backup-progress')
  banner.classList.toggle('hidden', progress.phase === 'complete' || progress.phase === 'error')
  banner.querySelector('strong').textContent = progress.phase === 'error' ? '备份失败' : '正在备份'
  banner.querySelector('p').textContent = progress.message || ''
  if (progress.phase === 'error') toast(progress.message, true)
})

loadAll().catch(error => toast(error.message, true))
