import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateMergePreflight } from './OCT14-MERGE-PREFLIGHT.mjs';
const head = 'a'.repeat(40), main = 'b'.repeat(40);
const pr = { state: 'open', head: { sha: head }, base: { ref: 'main' } };
const compare = { status: 'ahead', behind_by: 0, merge_base_commit: { sha: main } };
test('allows a reviewed head containing the actual current main tip', () => {
  assert.deepEqual(validateMergePreflight(pr, main, compare, head), { head, main });
});
test('refuses the captured stale-head case even when PR is conflict-free', () => {
  assert.throws(() => validateMergePreflight({ ...pr, mergeable: true }, main,
    { status: 'diverged', behind_by: 3, merge_base_commit: { sha: 'c'.repeat(40) } }, head), /main advanced/);
});
test('refuses missing or contradictory ancestry evidence', () => {
  for (const value of [null, {}, { ...compare, behind_by: 1 }, { ...compare, merge_base_commit: {} }, { ...compare, status: 'behind' }])
    assert.throws(() => validateMergePreflight(pr, main, value, head));
});
test('refuses changed head, closed PR, different base and invalid ref SHA', () => {
  assert.throws(() => validateMergePreflight(pr, main, compare, 'c'.repeat(40)), /head changed/);
  assert.throws(() => validateMergePreflight({ ...pr, state: 'closed' }, main, compare, head));
  assert.throws(() => validateMergePreflight({ ...pr, base: { ref: 'staging' } }, main, compare, head));
  assert.throws(() => validateMergePreflight(pr, 'unknown', compare, head));
});
test('accepts identical reviewed and main commits', () => {
  assert.deepEqual(validateMergePreflight(pr, head, { status: 'identical', behind_by: 0, merge_base_commit: { sha: head } }, head), { head, main: head });
});

test('reads the live main ref, not the stale PR base snapshot', async () => {
  const { checkCurrentMain } = await import('./OCT14-MERGE-PREFLIGHT.mjs');
  const get = path => path.endsWith('/git/ref/heads/main') ? { object: { sha: main } } :
    path.endsWith('/pulls/1299') ? { ...pr, base: { ref: 'main', sha: 'c'.repeat(40) } } : compare;
  assert.deepEqual(checkCurrentMain(head, get), { head, main });
});
test('refuses main changing during the read-only verification', async () => {
  const { checkCurrentMain } = await import('./OCT14-MERGE-PREFLIGHT.mjs');
  let reads = 0;
  const get = path => path.endsWith('/git/ref/heads/main') ? { object: { sha: ++reads === 1 ? main : 'c'.repeat(40) } } :
    path.endsWith('/pulls/1299') ? pr : compare;
  assert.throws(() => checkCurrentMain(head, get), /main changed during verification/);
});
