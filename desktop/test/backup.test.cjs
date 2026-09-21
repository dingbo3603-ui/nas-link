const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { hashFile, scanFolder } = require('../src/backup.cjs')

test('scans user files, hashes content, and ignores dependency caches', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nas-link-backup-'))
  fs.mkdirSync(path.join(root, '资料'), { recursive: true })
  fs.mkdirSync(path.join(root, 'node_modules', 'ignored'), { recursive: true })
  const wanted = path.join(root, '资料', '订单.txt')
  fs.writeFileSync(wanted, 'order-123')
  fs.writeFileSync(path.join(root, 'node_modules', 'ignored', 'large.bin'), 'ignore')
  const files = await scanFolder(root)
  assert.equal(files.length, 1)
  assert.equal(files[0].path, '资料/订单.txt')
  assert.equal(files[0].sha256, await hashFile(wanted))
})

