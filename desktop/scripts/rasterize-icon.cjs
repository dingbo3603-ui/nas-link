const sharp = require('sharp');
const path = require('node:path');

(async () => {
  const input = path.join(__dirname, '..', 'build', 'icon.svg');
  const output = path.join(__dirname, '..', 'build', 'icon.png');
  await sharp(input).resize(1024, 1024).png().toFile(output);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
