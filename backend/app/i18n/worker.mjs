// Translates backend text into Russian with the web UI's own dictionaries (frontend/src/i18n.ts, bundled into
// ru.mjs by `npm run build:i18n`). Protocol: one JSON array of strings per line in, the translations out.
import readline from 'node:readline'
import { tx } from './ru.mjs'

const rl = readline.createInterface({ input: process.stdin })
rl.on('line', (line) => {
  let out
  try {
    out = JSON.parse(line).map((text) => tx(text))
  } catch {
    out = []
  }
  process.stdout.write(JSON.stringify(out) + '\n')
})
