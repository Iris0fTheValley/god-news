import {staticFile} from 'remotion';

export const sourceForBrowser = (source: string | undefined): string | null => {
  if (!source) return null;
  if (/^(https?:|data:|blob:)/u.test(source)) return source;
  if (/^[a-zA-Z]:[\\/]/u.test(source) || source.startsWith('\\\\')) {
    return null;
  }
  return staticFile(source.replace(/^[/\\]+/u, '').replaceAll('\\', '/'));
};
