const { contextBridge, ipcRenderer, webUtils } = require('electron')

const listeners = new Map()

contextBridge.exposeInMainWorld('nasLink', {
  getConfig: () => ipcRenderer.invoke('config:get'),
  importConfig: () => ipcRenderer.invoke('config:import'),
  saveConfig: config => ipcRenderer.invoke('config:save', config),
  getDashboard: () => ipcRenderer.invoke('dashboard:get'),
  getDevices: () => ipcRenderer.invoke('devices:list'),
  getClipboard: () => ipcRenderer.invoke('clipboard:list'),
  sendCurrentClipboard: () => ipcRenderer.invoke('clipboard:send-current'),
  sendClipboard: text => ipcRenderer.invoke('clipboard:send', text),
  applyClipboard: text => ipcRenderer.invoke('clipboard:apply', text),
  clearClipboard: () => ipcRenderer.invoke('clipboard:clear'),
  getPathForFile: file => webUtils.getPathForFile(file),
  chooseAndUploadLibrary: () => ipcRenderer.invoke('library:choose-upload'),
  uploadLibraryPaths: paths => ipcRenderer.invoke('library:upload-paths', paths),
  listLibrary: status => ipcRenderer.invoke('library:list', status),
  searchLibrary: query => ipcRenderer.invoke('library:search', query),
  downloadLibraryFile: id => ipcRenderer.invoke('library:download', id),
  undoLibraryFile: id => ipcRenderer.invoke('library:undo', id),
  chooseAndSendFile: targetDevice => ipcRenderer.invoke('transfer:choose-send', targetDevice),
  listTransfers: () => ipcRenderer.invoke('transfer:list'),
  downloadTransfer: id => ipcRenderer.invoke('transfer:download', id),
  chooseBackupFolder: () => ipcRenderer.invoke('backup:choose-folder'),
  runBackup: folderPath => ipcRenderer.invoke('backup:run', folderPath),
  listBackups: () => ipcRenderer.invoke('backup:list'),
  getBackupManifest: snapshotId => ipcRenderer.invoke('backup:manifest', snapshotId),
  restoreBackupFile: (snapshotId, relativePath) => ipcRenderer.invoke('backup:restore', snapshotId, relativePath),
  openLocalPath: filePath => ipcRenderer.invoke('shell:show-item', filePath),
  on: (eventName, callback) => {
    const allowed = new Set(['connection', 'clipboard', 'file-offer', 'backup-progress', 'library-updated', 'library-upload-progress', 'config'])
    if (!allowed.has(eventName)) return () => {}
    const wrapped = (_event, payload) => callback(payload)
    ipcRenderer.on(`nas-link:${eventName}`, wrapped)
    listeners.set(callback, wrapped)
    return () => ipcRenderer.removeListener(`nas-link:${eventName}`, wrapped)
  }
})
