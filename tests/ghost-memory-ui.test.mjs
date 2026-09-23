import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const script = readFileSync(new URL('../dashboard/ghost.js', import.meta.url), 'utf8');

test('experience panel escapes remote titles and only links to EvoMap asset IDs', () => {
  const panel = { innerHTML: '' };
  const status = { memory: {
    inherited: 7, seeded: 0,
    last: { query: '<img src=x onerror=alert(1)>', weak: 0,
      hits: [{ title: '<script>alert(1)</script>', score: 0.8,
        steps: ['<svg onload=alert(1)>'] }] },
    evomap: { enabled: true, state: 'ready', event: 'trip', references: [
      { title: '<img src=x onerror=alert(2)>', type: 'Gene', trust_tier: 'normal',
        validation_status: 'noop',
        url: `https://evomap.ai/a2a/assets/sha256:${'a'.repeat(64)}` },
      { title: 'malicious URL', url: 'javascript:alert(3)' },
    ] },
  } };
  vm.runInNewContext(`${script}\nGhost.update(status);`, {
    document: { getElementById: id => id === 'gMemory' ? panel : null }, status,
  });
  assert.match(panel.innerHTML, /&lt;script&gt;/);
  assert.match(panel.innerHTML, /&lt;svg/);
  assert.match(panel.innerHTML, /https:\/\/evomap\.ai\/a2a\/assets\/sha256:/);
  assert.doesNotMatch(panel.innerHTML, /<script|<svg|javascript:|malicious URL/);
});
