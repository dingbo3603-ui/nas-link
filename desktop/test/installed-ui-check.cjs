const { WebSocket } = require('ws')

const endpoint = process.argv[2]
if (!endpoint) throw new Error('DevTools WebSocket endpoint is required')

const socket = new WebSocket(endpoint)
socket.on('open', () => {
  socket.send(JSON.stringify({
    id: 1,
    method: 'Runtime.evaluate',
    params: {
      expression: `JSON.stringify({
        title: document.querySelector('#connection-title')?.textContent,
        detail: document.querySelector('#connection-detail')?.textContent,
        dotConnected: document.querySelector('#connection-dot')?.classList.contains('connected')
      })`,
      returnByValue: true,
    },
  }))
})
socket.on('message', raw => {
  const message = JSON.parse(String(raw))
  if (message.id !== 1) return
  const value = message.result?.result?.value
  if (!value) throw new Error('Connection UI state was unavailable')
  console.log(value)
  socket.close()
})
socket.on('error', error => {
  console.error(error.message)
  process.exitCode = 1
})
