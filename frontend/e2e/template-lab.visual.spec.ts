import {expect, test} from '@playwright/test';
import {copyFile, mkdir, rm} from 'node:fs/promises';
import path from 'node:path';

const hostSource = process.env.GOD_NEWS_TEMPLATE_LAB_HOST_VIDEO;
const hostPublicPath = path.resolve('public/template-lab/e2e-host.webm');
const hostBrowserUrl = '/template-lab/e2e-host.webm';

test.beforeAll(async () => {
  if (!hostSource) return;
  await mkdir(path.dirname(hostPublicPath), {recursive: true});
  await copyFile(path.resolve(hostSource), hostPublicPath);
});

test.afterAll(async () => {
  if (!hostSource) return;
  await rm(hostPublicPath, {force: true});
});

const cases = [
  {
    name: 'evidence-horizontal',
    query:
      'fixture=evidence-source-page&scene=evidence_fullscreen&variant=evidence_documentary&profile=bilibili_horizontal&frame=90&zoom=0.48',
  },
  {
    name: 'host-split-horizontal',
    requiresHost: true,
    query:
      `fixture=host-volunteers&scene=host_evidence&variant=host_split_editorial&profile=bilibili_horizontal&frame=90&zoom=0.48&host=1&hostVideo=${encodeURIComponent(hostBrowserUrl)}`,
  },
  {
    name: 'host-corner-vertical',
    requiresHost: true,
    query:
      `fixture=host-corner-volunteers&scene=host_evidence&variant=host_corner_full_bleed&profile=douyin_vertical&frame=90&zoom=0.36&host=1&hostSlot=corner&hostVideo=${encodeURIComponent(hostBrowserUrl)}`,
  },
  {
    name: 'long-caption-vertical',
    query:
      'fixture=evidence-long-caption&scene=evidence_fullscreen&variant=evidence_documentary&profile=douyin_vertical&frame=90&zoom=0.36',
  },
  {
    name: 'source-video-horizontal',
    query:
      'fixture=source-video-owned&scene=source_video&variant=source_video_clean&profile=bilibili_horizontal&frame=90&zoom=0.48',
  },
] as const;

for (const fixture of cases) {
  test(`${fixture.name} uses decodable production media without overflow`, async ({
    page,
  }, testInfo) => {
    test.skip(
      'requiresHost' in fixture && fixture.requiresHost && !hostSource,
      'Set GOD_NEWS_TEMPLATE_LAB_HOST_VIDEO to a reviewed pre-rendered Live2D WebM.',
    );
    const browserErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(message.text());
    });
    page.on('pageerror', (error) => browserErrors.push(String(error)));
    await page.goto(`/template-lab?${fixture.query}`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(800);

    await expect(page.locator('[data-scene-module]')).toHaveCount(1);
    for (const image of await page.locator('img').all()) {
      await expect
        .poll(() =>
          image.evaluate(
            (element) => {
              const candidate = element as HTMLImageElement;
              return Boolean(
                candidate.complete &&
                  candidate.naturalWidth > 0 &&
                  candidate.naturalHeight > 0,
              );
            },
          ),
        )
        .toBe(true);
    }
    for (const video of await page.locator('video').all()) {
      await expect
        .poll(() =>
          video.evaluate(
            (element) => {
              const candidate = element as HTMLVideoElement;
              return Boolean(
                candidate.readyState >= 2 &&
                  candidate.videoWidth > 0 &&
                  candidate.videoHeight > 0,
              );
            },
          ),
        )
        .toBe(true);
    }
    for (const caption of await page.locator('[data-caption-region]').all()) {
      const overflow = await caption.evaluate(
        (element) =>
          element.scrollWidth > element.clientWidth + 1 ||
          element.scrollHeight > element.clientHeight + 1,
      );
      expect(overflow).toBe(false);
    }
    expect(browserErrors).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`${fixture.name}.png`),
      fullPage: true,
    });
  });
}
