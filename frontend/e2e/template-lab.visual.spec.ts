import {expect, test} from '@playwright/test';
import type {Locator, Page} from '@playwright/test';
import {copyFile, mkdir, rm} from 'node:fs/promises';
import path from 'node:path';

const hostSource = process.env.GOD_NEWS_TEMPLATE_LAB_HOST_VIDEO;
const hostPublicPath = path.resolve('public/template-lab/e2e-host.webm');
const hostBrowserUrl = '/template-lab/e2e-host.webm';

test.beforeAll(async () => {
  if (!hostSource) {
    throw new Error(
      'GOD_NEWS_TEMPLATE_LAB_HOST_VIDEO must point to a real pre-rendered Live2D WebM.',
    );
  }
  await mkdir(path.dirname(hostPublicPath), {recursive: true});
  await copyFile(path.resolve(hostSource), hostPublicPath);
});

test.afterAll(async () => {
  await rm(hostPublicPath, {force: true});
});

const currentFrame = async (page: Page): Promise<number> => {
  const text = await page.getByTestId('template-lab-current-frame').innerText();
  const match = /FRAME\s+(\d+)/u.exec(text);
  if (!match) throw new Error(`Unable to parse Template Lab frame: ${text}`);
  return Number(match[1]);
};

const renderedHostSignature = async (
  page: Page,
  video: Locator,
  outputPath?: string,
): Promise<number[]> => {
  const screenshot = await video.screenshot({
    ...(outputPath ? {path: outputPath} : {}),
    type: 'jpeg',
    quality: 70,
  });
  return page.evaluate(async (dataUrl) => {
    const response = await fetch(dataUrl);
    const bitmap = await createImageBitmap(await response.blob());
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) throw new Error('Canvas 2D context is unavailable.');
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const signature: number[] = [];
    for (let index = 0; index < pixels.length; index += 4) {
      signature.push(
        Math.round(
          (299 * (pixels[index] ?? 0) +
            587 * (pixels[index + 1] ?? 0) +
            114 * (pixels[index + 2] ?? 0)) /
            1_000,
        ),
      );
    }
    return signature;
  }, `data:image/jpeg;base64,${screenshot.toString('base64')}`);
};

const signatureDelta = (left: number[], right: number[]): number => {
  expect(left).toHaveLength(right.length);
  return left.reduce(
    (total, value, index) => total + Math.abs(value - (right[index] ?? 0)),
    0,
  ) / left.length;
};

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
      `fixture=host-volunteers&scene=host_evidence&variant=host_split_editorial&profile=bilibili_horizontal&frame=0&zoom=0.48&host=1&hostVideo=${encodeURIComponent(hostBrowserUrl)}`,
  },
  {
    name: 'host-corner-vertical',
    requiresHost: true,
    query:
      `fixture=host-corner-volunteers&scene=host_evidence&variant=host_corner_full_bleed&profile=douyin_vertical&frame=0&zoom=0.36&host=1&hostSlot=corner&hostVideo=${encodeURIComponent(hostBrowserUrl)}`,
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
    if ('requiresHost' in fixture && fixture.requiresHost) {
      const host = page.locator('video[data-host-segment-id]');
      await expect(host).toHaveCount(1);
      await expect
        .poll(() =>
          host.evaluate((element) => {
            const video = element as HTMLVideoElement;
            return `${video.videoWidth}x${video.videoHeight}`;
          }),
        )
        .toBe('720x720');
      const initialFrame = await currentFrame(page);
      const initialTime = await host.evaluate(
        (element) => (element as HTMLVideoElement).currentTime,
      );
      await page.getByTestId('template-lab-play-pause').click();
      const playerFrame = page.getByTestId('template-lab-player-frame');
      await expect(playerFrame).toHaveAttribute('data-playback-state', 'playing');
      await expect
        .poll(() => currentFrame(page), {timeout: 5_000})
        .toBeGreaterThanOrEqual(initialFrame + 50);

      const signatures: number[][] = [];
      let sampledTime = await host.evaluate(
        (element) => (element as HTMLVideoElement).currentTime,
      );
      for (let index = 0; index < 4; index += 1) {
        await expect
          .poll(
            () =>
              host.evaluate(
                (element) => (element as HTMLVideoElement).currentTime,
              ),
            {timeout: 3_000},
          )
          .toBeGreaterThan(sampledTime + 0.2);
        sampledTime = await host.evaluate(
          (element) => (element as HTMLVideoElement).currentTime,
        );
        signatures.push(
          await renderedHostSignature(
            page,
            host,
            testInfo.outputPath(`${fixture.name}-host-dynamic-${index}.jpg`),
          ),
        );
        await playerFrame.screenshot({
          path: testInfo.outputPath(`${fixture.name}-dynamic-${index}.png`),
        });
      }
      const advancedTime = await host.evaluate(
        (element) => (element as HTMLVideoElement).currentTime,
      );
      expect(advancedTime - initialTime).toBeGreaterThan(2);
      const dynamicDeltas = signatures.slice(1).map((signature, index) =>
        signatureDelta(signatures[index] ?? [], signature),
      );
      expect(dynamicDeltas.filter((delta) => delta >= 0.25)).toHaveLength(3);

      await page.getByTestId('template-lab-play-pause').click();
      await expect(playerFrame).toHaveAttribute('data-playback-state', 'paused');
      await expect
        .poll(() =>
          host.evaluate((element) => (element as HTMLVideoElement).paused),
        )
        .toBe(true);
      const pausedTime = await host.evaluate(
        (element) => (element as HTMLVideoElement).currentTime,
      );
      const pausedFrame = await currentFrame(page);
      const pausedSignature = await renderedHostSignature(
        page,
        host,
        testInfo.outputPath(`${fixture.name}-paused-before.jpg`),
      );
      await page.waitForTimeout(350);
      expect(
        await host.evaluate(
          (element) => (element as HTMLVideoElement).currentTime,
        ),
      ).toBe(pausedTime);
      expect(await currentFrame(page)).toBe(pausedFrame);
      const pausedAfterSignature = await renderedHostSignature(
        page,
        host,
        testInfo.outputPath(`${fixture.name}-paused-after.jpg`),
      );
      // Repeated same-frame Edge captures varied by at most 0.0098 mean
      // grayscale levels, while the smallest observed real-motion delta was
      // 0.846. This keeps a wide separation between compositor rounding and
      // visible motion without treating exact PNG bytes as a playback clock.
      expect(signatureDelta(pausedSignature, pausedAfterSignature)).toBeLessThanOrEqual(
        0.05,
      );
      await page.getByTestId('template-lab-next-frame').click();
      await expect.poll(() => currentFrame(page)).toBe(pausedFrame + 1);
      await page.getByTestId('template-lab-play-pause').click();
      await expect(playerFrame).toHaveAttribute('data-playback-state', 'playing');
      await expect
        .poll(() => currentFrame(page), {timeout: 3_000})
        .toBeGreaterThan(pausedFrame + 10);
      await page.getByTestId('template-lab-play-pause').click();
      await expect(playerFrame).toHaveAttribute('data-playback-state', 'paused');
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
