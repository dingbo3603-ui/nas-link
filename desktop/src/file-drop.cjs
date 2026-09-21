const fs = require('node:fs')
const path = require('node:path')

const MAX_DROP_FILES = 500

async function selectUploadFiles (inputPaths, fileSystem = fs.promises) {
  const accepted = []
  const rejected = []
  const seen = new Set()
  const candidates = Array.isArray(inputPaths) ? inputPaths.slice(0, MAX_DROP_FILES) : []

  for (const input of candidates) {
    if (typeof input !== 'string' || !input.trim()) continue
    const absolute = path.resolve(input)
    const key = process.platform === 'win32' ? absolute.toLowerCase() : absolute
    if (seen.has(key)) continue
    seen.add(key)

    try {
      const stat = await fileSystem.stat(absolute)
      if (!stat.isFile()) {
        rejected.push({ name: path.basename(absolute), reason: '暂不支持直接拖入文件夹' })
        continue
      }
      accepted.push({ path: absolute, name: path.basename(absolute), size: stat.size })
    } catch {
      rejected.push({ name: path.basename(absolute) || '未知文件', reason: '文件不存在或无法读取' })
    }
  }

  if (Array.isArray(inputPaths) && inputPaths.length > MAX_DROP_FILES) {
    rejected.push({ name: '其余文件', reason: `单次最多处理 ${MAX_DROP_FILES} 个文件` })
  }
  return { accepted, rejected }
}

module.exports = { MAX_DROP_FILES, selectUploadFiles }
