const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { MAX_DROP_FILES, selectUploadFiles } = require('../src/file-drop.cjs')

test('accepts readable files, removes duplicates, and rejects folders', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nas-link-drop-'))
  const file = path.join(root, '订单.txt')
  fs.writeFileSync(file, 'order-123')

  const result = await selectUploadFiles([file, file, root, path.join(root, 'missing.pdf')])

  assert.equal(result.accepted.length, 1)
  assert.equal(result.accepted[0].name, '订单.txt')
  assert.equal(result.accepted[0].size, 9)
  assert.deepEqual(result.rejected.map(item => item.reason), [
    '暂不支持直接拖入文件夹',
    '文件不存在或无法读取'
  ])
  assert.equal(MAX_DROP_FILES, 500)
})
