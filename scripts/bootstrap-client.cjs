const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { ConfigStore } = require('../desktop/src/config.cjs');

const sourcePath = path.resolve(process.argv[2] || path.join(__dirname, '..', 'release', 'nas-link-client-config.json'));
const appData = process.env.APPDATA;
if (!appData) throw new Error('APPDATA is unavailable');

const input = JSON.parse(fs.readFileSync(sourcePath, 'utf8'));
if (!input.serverUrl || !input.token) throw new Error('Connection file is incomplete');

const targetPath = path.join(appData, 'nas-link-desktop', 'config.json');
if (fs.existsSync(targetPath)) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  fs.copyFileSync(targetPath, `${targetPath}.backup-${stamp}`);
}

const store = new ConfigStore(targetPath);
const config = store.update({
  serverUrl: input.serverUrl,
  token: input.token,
  deviceName: store.value.deviceName || os.hostname(),
});

console.log(JSON.stringify({
  configured: true,
  targetPath,
  serverUrl: config.serverUrl,
  deviceName: config.deviceName,
  tokenPresent: Boolean(config.token),
}, null, 2));
