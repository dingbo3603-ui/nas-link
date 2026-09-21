const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { MAX_DROP_FILES, describeFileAccessError, selectUploadFiles } = require('../src/file-drop.cjs')

test('accepts readable files, removes duplicates, and recursively scans folders', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nas-link-drop-'))
  const file = path.join(root, '订单.txt')
  const nested = path.join(root, '图片')
  fs.mkdirSync(nested)
  fs.writeFileSync(file, 'order-123')
  fs.writeFileSync(path.join(nested, '产品图.jpg'), 'image')

  const result = await selectUploadFiles([file, file, root, path.join(root, 'missing.pdf')])

  assert.equal(result.accepted.length, 2)
  assert.deepEqual(result.accepted.map(item => item.name).sort(), ['产品图.jpg', '订单.txt'].sort())
  assert.deepEqual(result.rejected.map(item => item.reason), [
    '找不到这个文件；如果它来自照片应用、浏览器或云盘，请先保存或下载到本地磁盘后再拖入'
  ])
  assert.equal(MAX_DROP_FILES, 10_000)
})

test('rejects a file that exists but cannot actually be opened', async () => {
  const denied = Object.assign(new Error('operation not permitted'), { code: 'EPERM' })
  const fileSystem = {
    stat: async () => ({ isFile: () => true, size: 42 }),
    open: async () => { throw denied }
  }
  const result = await selectUploadFiles(['/Users/test/Desktop/photo.jpg'], fileSystem)

  assert.equal(result.accepted.length, 0)
  assert.equal(result.rejected.length, 1)
  assert.match(result.rejected[0].reason, /系统没有读取权限/)
})

test('explains temporary and cloud-backed paths that have disappeared', () => {
  assert.match(describeFileAccessError({ code: 'ENOENT' }), /本地磁盘/)
})
