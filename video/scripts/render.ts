import {createHash} from 'node:crypto';
import {copyFile, mkdir, mkdtemp, readFile, rm, stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename, dirname, extname, isAbsolute, join, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';

import {COMPOSITION_ID} from '../src/constants';
import {
  parseGodNewsVideoProps,
  type GodNewsVideoProps,
} from '../src/schema';

type CliOptions = Readonly<{
  input: string;
  output?: string;
  concurrency?: number;
}>;

const usage = `Usage:
  pnpm render -- --input <video-props.json> [--output <video.mp4>] [--concurrency <n>]

Local audio_path and bgm.local_path values are resolved relative to the JSON file.`;

const parseArgs = (args: readonly string[]): CliOptions => {
  const normalizedArgs = args[0] === '--' ? args.slice(1) : args;
  if (normalizedArgs.includes('--help') || normalizedArgs.includes('-h')) {
    process.stdout.write(`${usage}\n`);
    process.exit(0);
  }

  const values = new Map<string, string>();
  for (let index = 0; index < normalizedArgs.length; index += 2) {
    const flag = normalizedArgs[index];
    const value = normalizedArgs[index + 1];
    if (!flag?.startsWith('--') || !value || value.startsWith('--')) {
      throw new Error(`Invalid argument near ${flag ?? '<end>'}.\n${usage}`);
    }
    values.set(flag, value);
  }

  const input = values.get('--input');
  if (!input) throw new Error(`--input is required.\n${usage}`);
  const unknown = [...values.keys()].filter(
    (key) => !['--input', '--output', '--concurrency'].includes(key),
  );
  if (unknown.length > 0) {
    throw new Error(`Unknown option: ${unknown.join(', ')}.\n${usage}`);
  }

  const concurrencyValue = values.get('--concurrency');
  const concurrency = concurrencyValue ? Number(concurrencyValue) : undefined;
  const output = values.get('--output');
  if (
    concurrency !== undefined &&
    (!Number.isInteger(concurrency) || concurrency < 1)
  ) {
    throw new Error('--concurrency must be a positive integer.');
  }

  return {
    input,
    ...(output ? {output} : {}),
    ...(concurrency !== undefined ? {concurrency} : {}),
  };
};

const sha256 = async (path: string): Promise<string> => {
  const hash = createHash('sha256');
  hash.update(await readFile(path));
  return hash.digest('hex');
};

const resolveLocalAsset = (source: string, inputDirectory: string): string => {
  if (/^[a-zA-Z][a-zA-Z\d+.-]*:/u.test(source) && !/^[a-zA-Z]:[\\/]/u.test(source)) {
    throw new Error(`Remote or URI assets are not allowed in deterministic renders: ${source}`);
  }
  return isAbsolute(source) ? resolve(source) : resolve(inputDirectory, source);
};

const stageAsset = async (
  source: string,
  inputDirectory: string,
  publicDirectory: string,
): Promise<string> => {
  const absolute = resolveLocalAsset(source, inputDirectory);
  const info = await stat(absolute);
  if (!info.isFile()) throw new Error(`Asset is not a file: ${absolute}`);

  const digest = await sha256(absolute);
  const suffix = extname(absolute).toLowerCase() || '.bin';
  const relative = `assets/${digest}${suffix}`;
  const destination = join(publicDirectory, ...relative.split('/'));
  await mkdir(dirname(destination), {recursive: true});
  await copyFile(absolute, destination);
  return relative;
};

const stageProps = async (
  props: GodNewsVideoProps,
  inputDirectory: string,
  publicDirectory: string,
): Promise<GodNewsVideoProps> => {
  const audioEntries = await Promise.all(
    props.manifest.timeline.map(async (segment) => [
      segment.segment_id,
      await stageAsset(segment.audio_path, inputDirectory, publicDirectory),
    ] as const),
  );
  const bgmSrc = props.bgm
    ? await stageAsset(props.bgm.local_path, inputDirectory, publicDirectory)
    : undefined;

  return parseGodNewsVideoProps({
    ...props,
    runtime_assets: {
      audio_by_segment_id: Object.fromEntries(audioEntries),
      ...(bgmSrc ? {bgm_src: bgmSrc} : {}),
    },
  });
};

const safelyRemoveWorkspace = async (workspace: string): Promise<void> => {
  const resolvedWorkspace = resolve(workspace);
  const resolvedTemp = resolve(tmpdir());
  const expectedPrefix = `${resolvedTemp}${sep}god-news-remotion-`;
  if (!resolvedWorkspace.startsWith(expectedPrefix)) {
    throw new Error(`Refusing to remove unexpected render workspace: ${resolvedWorkspace}`);
  }
  await rm(resolvedWorkspace, {recursive: true, force: true});
};

const main = async (): Promise<void> => {
  const options = parseArgs(process.argv.slice(2));
  const inputPath = resolve(options.input);
  const raw = JSON.parse(await readFile(inputPath, 'utf8')) as unknown;
  const props = parseGodNewsVideoProps(raw);
  const outputPath = resolve(
    options.output ?? join('out', `${props.manifest.story_id}.mp4`),
  );
  const workspace = await mkdtemp(join(tmpdir(), 'god-news-remotion-'));

  try {
    const publicDirectory = join(workspace, 'public');
    const bundleDirectory = join(workspace, 'bundle');
    await mkdir(publicDirectory, {recursive: true});
    const stagedProps = await stageProps(
      props,
      dirname(inputPath),
      publicDirectory,
    );
    const packageDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '..');
    const serveUrl = await bundle({
      entryPoint: join(packageDirectory, 'src', 'index.ts'),
      publicDir: publicDirectory,
      outDir: bundleDirectory,
    });
    const composition = await selectComposition({
      serveUrl,
      id: COMPOSITION_ID,
      inputProps: stagedProps,
    });

    await mkdir(dirname(outputPath), {recursive: true});
    await renderMedia({
      composition,
      serveUrl,
      codec: 'h264',
      outputLocation: outputPath,
      inputProps: stagedProps,
      overwrite: true,
      ...(options.concurrency ? {concurrency: options.concurrency} : {}),
    });
    process.stdout.write(
      `${JSON.stringify({story_id: props.manifest.story_id, output: outputPath})}\n`,
    );
  } finally {
    await safelyRemoveWorkspace(workspace);
  }
};

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Render failed: ${message}\n`);
  process.exitCode = 1;
});
