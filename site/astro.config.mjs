// @ts-check
import { defineConfig } from 'astro/config';

// SITE e BASE vêm do GitHub Actions (ex.: https://usuario.github.io/monitor-maringa)
export default defineConfig({
  site: process.env.SITE ?? 'http://localhost:4321',
  base: process.env.BASE ?? '/',
  trailingSlash: 'always',
});
