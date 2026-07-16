/* global Buffer, process */

import {chromium} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
import path from 'node:path';

const valueAfter = (flag) => {
  const index = process.argv.indexOf(flag);
  return index >= 0 ? process.argv[index + 1] : undefined;
};

const encodedUrl = valueAfter('--url-base64');
const url = valueAfter('--url') ?? (encodedUrl ? Buffer.from(encodedUrl, 'base64').toString('utf8') : undefined);
const output = valueAfter('--output');
if (!url || !output) {
  throw new Error(
    'Usage: pnpm capture:template-lab -- --url-base64 <base64-url> --output <png-path>',
  );
}
const target = path.resolve(output);
await mkdir(path.dirname(target), {recursive: true});
const browser = await chromium.launch({channel: 'msedge', headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
  const errors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(String(error)));
  await page.goto(url, {waitUntil: 'networkidle'});
  await page.waitForTimeout(800);
  if (errors.length > 0) {
    throw new Error(`Template Lab emitted browser errors: ${errors.join(' | ')}`);
  }
  await page.screenshot({path: target, fullPage: true});
  process.stdout.write(`${target}\n`);
} finally {
  await browser.close();
}
