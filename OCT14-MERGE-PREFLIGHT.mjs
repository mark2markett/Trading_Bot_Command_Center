// Read-only check: PR.base.sha is not a substitute for the current main ref.
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export function validateMergePreflight(pr, main, comparison, expected) {
  if (!/^[a-f0-9]{40}$/.test(expected) || !/^[a-f0-9]{40}$/.test(main))
    throw new Error('Invalid release or main SHA; no merge was attempted.');
  if (pr?.state !== 'open' || pr?.base?.ref !== 'main')
    throw new Error('PR is not open against main; no merge was attempted.');
  if (pr?.head?.sha !== expected)
    throw new Error('PR head changed; fresh current-head review is required.');
  if (!comparison || !['ahead', 'identical'].includes(comparison.status) ||
      comparison.behind_by !== 0 || comparison.merge_base_commit?.sha !== main)
    throw new Error('main advanced beyond the reviewed branch. Integrate main and obtain fresh checks/review; no merge was attempted.');
  return { head: expected, main };
}

function readApi(path) {
  return JSON.parse(execFileSync('gh', ['api', path], {
    encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
  }));
}

export function checkCurrentMain(expected, get = readApi) {
  const prefix = 'repos/mark2markett/m2m-platform';
  const main = get(`${prefix}/git/ref/heads/main`).object?.sha;
  if (!/^[a-f0-9]{40}$/.test(main || '')) throw new Error('Cannot verify the current main ref.');
  const pr = get(`${prefix}/pulls/1299`);
  const comparison = get(`${prefix}/compare/${main}...${expected}`);
  const result = validateMergePreflight(pr, main, comparison, expected);
  if (get(`${prefix}/git/ref/heads/main`).object?.sha !== main)
    throw new Error('main changed during verification; no merge was attempted.');
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { console.log(JSON.stringify(checkCurrentMain(process.argv[2]))); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
