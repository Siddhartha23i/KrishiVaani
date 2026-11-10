import { existsSync } from 'node:fs';

if (existsSync('.env')) process.loadEnvFile('.env');

export default {
  sessionId: "telangana-farmer-whatsapp",
  host: '127.0.0.1',
  apiKey: process.env.WA_API_KEY || undefined,
  browser: { source: 'auto' },
};
