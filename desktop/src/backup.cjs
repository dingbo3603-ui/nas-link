const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')

const DEFAULT_IGNORED_DIRECTORIES = new Set([
  '.git', '.svn', 'node_modules', '__pycache__', '.pytest_cache', '.venv', 'venv',
  '$RECYCLE.BIN', 'System Volume Information', '.Trash', '.Trashes'
])

async function hashFile (filePath) {
  return await new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256')
    const stream = fs.createReadStream(filePath)
    stream.on('data', chunk => hash.update(chunk))
    stream.on('error', reject)
    stream.on('end', () => resolve(hash.digest('hex')))
  })
}

async function scanFolder (rootPath, onProgress = () => {}) {
  const root = path.resolve(rootPath)
  const files = []
  const queue = [root]
  let scanned = 0
  while (queue.length) {
    const current = queue.pop()
    let entries
    try {
      entries = await fs.promises.readdir(current, { withFileTypes: true })
    } catch {
      continue
    }
    for (const entry of entries) {
      if (entry.isSymbolicLink()) continue
      if (entry.isDirectory() && DEFAULT_IGNORED_DIRECTORIES.has(entry.name)) continue
      const absolute = path.join(current, entry.name)
      if (entry.isDirectory()) {
        queue.push(absolute)
        continue
      }
      if (!entry.isFile()) continue
      try {
        const stat = await fs.promises.stat(absolute)
        const sha256 = await hashFile(absolute)
        files.push({
          absolute,
          path: path.relative(root, absolute).split(path.sep).join('/'),
          sha256,
          size: stat.size,
          mtime_ns: Math.round(stat.mtimeMs * 1_000_000)
        })
        scanned += 1
        onProgress({ phase: 'scan', scanned, current: entry.name })
      } catch {
        // A file may disappear while a live directory is being scanned; skip and report at summary level.
      }
    }
  }
  return files
}

module.exports = { DEFAULT_IGNORED_DIRECTORIES, hashFile, scanFolder }

