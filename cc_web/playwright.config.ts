import { defineConfig } from '@playwright/test'
export default defineConfig({ testDir: './e2e', timeout: 30000, use: { viewport: { width: 1440, height: 1000 }, launchOptions: { executablePath: '/opt/pw-browsers/chromium' } }, reporter: 'list' })
