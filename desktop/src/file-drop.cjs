const fs = require('node:fs')
const path = require('node:path')

const MAX_DROP_FILES = 10_000

function describeFileAccessError (error) {
  const code = error?.code
  if (code === 'EACCES' || code === 'EPERM') {
    return '系统没有读取权限。请检查文件或文件夹的安全权限，或先复制到本机“下载”文件夹后重试'
  }
  if (code === 'ENOENT') {
    return '找不到这个文件；如果它来自照片应用、浏览器或云盘，请先保存或下载到本地磁盘后再拖入'
  }
  if (code === 'EBUSY') return '文件正在被其他程序占用，请关闭占用它的程序后重试'
  return '本机无法读取这个文件'
}

async function selectUploadFiles (inputPaths, fileSystem = fs.promises) {
  const accepted = []
  const rejected = []
  const seen = new Set()
  let truncated = false

  async function visit (absolute) {
    if (accepted.length >= MAX_DROP_FILES) {
      truncated = true
      return
    }
    const key = process.platform === 'win32' ? absolute.toLowerCase() : absolute
    if (seen.has(key)) return
    seen.add(key)

    try {
      const stat = fileSystem.lstat ? await fileSystem.lstat(absolute) : await fileSystem.stat(absolute)
      if (stat.isSymbolicLink?.()) {
        rejected.push({ name: path.basename(absolute), reason: '为避免循环扫描，暂不跟随快捷方式或符号链接' })
        return
      }
      if (stat.isDirectory?.()) {
        const entries = await fileSystem.readdir(absolute, { withFileTypes: true })
        entries.sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'))
        for (const entry of entries) {
          await visit(path.join(absolute, entry.name))
          if (truncated) break
        }
        return
      }
      if (!stat.isFile()) {
        rejected.push({ name: path.basename(absolute), reason: '不是可上传的普通文件' })
        return
      }
      const handle = await fileSystem.open(absolute, 'r')
      await handle.close()
      accepted.push({ path: absolute, name: path.basename(absolute), size: stat.size })
    } catch (error) {
      rejected.push({ name: path.basename(absolute) || '未知文件', reason: describeFileAccessError(error) })
    }
  }

  const candidates = Array.isArray(inputPaths) ? inputPaths : []
  for (const input of candidates) {
    if (typeof input !== 'string' || !input.trim()) continue
    const absolute = path.resolve(input)
    await visit(absolute)
    if (truncated) break
  }

  if (truncated) {
    rejected.push({ name: '其余文件', reason: `单次最多处理 ${MAX_DROP_FILES} 个文件；更大的目录请使用“备份中心”` })
  }
  return { accepted, rejected }
}

module.exports = { MAX_DROP_FILES, describeFileAccessError, selectUploadFiles }
