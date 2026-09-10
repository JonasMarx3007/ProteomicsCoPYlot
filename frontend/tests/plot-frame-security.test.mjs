import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';

test('every generated-content feature iframe is sandboxed without same-origin privileges', async () => {
  const root = new URL('../src/features/', import.meta.url);
  let frames = 0;
  for (const path of await readdir(root, { recursive: true })) {
    if (!path.endsWith('.tsx')) continue;
    const text = await readFile(new URL(path.replaceAll('\\', '/'), root), 'utf8');
    for (const tag of text.matchAll(/<iframe\b[^>]*>/g)) {
      frames++;
      assert.match(tag[0], /sandbox="allow-scripts allow-downloads"/, path);
      assert.doesNotMatch(tag[0], /allow-same-origin/, path);
    }
  }
  assert.ok(frames >= 7);
});
