import {copyFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const repositoryRoot = path.resolve(frontendRoot, '..');
const sourceRoot = path.join(repositoryRoot, 'assets', 'demo-owned');
const targetRoot = path.join(frontendRoot, 'public', 'template-lab');

const files = [
  'community-library-source.png',
  'library-volunteers-low-res.png',
  'library-volunteers-low-res.provenance.json',
  'library-volunteers.png',
  'project-owned-source.mp4',
  'project-owned-source.provenance.json',
];

await mkdir(targetRoot, {recursive: true});
await Promise.all(
  files.map((name) =>
    copyFile(path.join(sourceRoot, name), path.join(targetRoot, name)),
  ),
);
