import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import ts from 'typescript';

const module = { exports: {} };
const code = ts.transpileModule(
  readFileSync('apps/web/app/grupo/route.ts', 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText;
new Function('require', 'module', 'exports', code)(createRequire(import.meta.url), module, module.exports);
const { GET, HEAD } = module.exports;
const destination = 'https://chat.whatsapp.com/FiK8zZOYcj75lggiCfsNaq?s=cl&p=i&iam=2';

for (const method of ['GET', 'HEAD']) {
  for (const query of ['', '?url=https://evil.invalid&phone=private&utm_source=facebook']) {
    test(`${method} redirects only to the approved group without forwarding input ${query ? '(query)' : ''}`, async () => {
      const response = await ({ GET, HEAD }[method])(
        new Request(`https://jardinesdelencanto.site/grupo${query}`, { method }),
      );
      assert.equal(response.status, 302);
      assert.equal(response.headers.get('location'), destination);
      assert.equal(response.headers.get('cache-control'), 'no-store');
      assert.equal(response.headers.get('x-robots-tag'), 'noindex, nofollow');
      assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
      assert.equal(await response.text(), '');
    });
  }
}

test('the deployed handler preserves redirect headers through Next.js', {
  skip: !process.env.LANDING_BASE_URL,
}, async () => {
  for (const method of ['GET', 'HEAD']) {
    const response = await fetch(
      `${process.env.LANDING_BASE_URL}/grupo?url=https://evil.invalid&phone=private`,
      { method, redirect: 'manual' },
    );
    assert.equal(response.status, 302);
    assert.equal(response.headers.get('location'), destination);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.equal(response.headers.get('x-robots-tag'), 'noindex, nofollow');
    assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
    assert.equal(await response.text(), '');
  }
});
