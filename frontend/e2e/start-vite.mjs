// Cross-platform vite dev server for Playwright webServer (Linux/macOS/Windows).
import { spawn } from 'node:child_process'

const env = {
  ...process.env,
  VITE_PROXY_TARGET: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8086',
  VITE_ENABLE_ADVANCED_TOOLS: 'true',
}

const child = spawn(
  process.platform === 'win32' ? 'npm.cmd' : 'npm',
  ['run', 'dev', '--', '--port', '3000', '--host', '127.0.0.1'],
  { stdio: 'inherit', env, shell: process.platform === 'win32' },
)

child.on('exit', (code) => process.exit(code ?? 1))
