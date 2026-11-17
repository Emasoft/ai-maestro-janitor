// secrets-shield redact, write guards (TRDD-BAQB9SYO increment 3): the write-target guard of step 3a-3a, checked just before a file is replaced, and the atomic write and the git-operation check, moved here from worker.ts in step 3a-4a so restore.ts can share them.
// WHY: the walker looks at a file with lstat once, when it lists it, and the worker then opens and realpaths the path, both of which follow symlinks. A file that became a symlink (or sits behind a folder that became one) during a long run would have its target rewritten, possibly outside the scanned root. The check runs again at the last moment: the path must still be a regular file, not a symlink, and its real path must lie strictly inside the real path of the scan root.
// The window between this check and the rename is not closed (stated, like the one in writeAtomic).

import { spawnSync } from 'node:child_process'
import { closeSync, existsSync, fchmodSync, fsyncSync, lstatSync, openSync, realpathSync, renameSync, statSync, unlinkSync, writeFileSync, type BigIntStats } from 'node:fs'
import { dirname, join, resolve, sep } from 'node:path'
import { findGitTop } from './fileset.ts'
import type { WriteSkipReason } from './redact.ts'

export function checkWriteTarget(path: string, root: string): 'ok' | Extract<WriteSkipReason, 'not-regular-at-write' | 'outside-root'> {
  try {
    // lstat does not follow the last component: a symlink is not a regular file here.
    if (!lstatSync(path).isFile()) return 'not-regular-at-write'
  } catch {
    return 'not-regular-at-write'
  }
  try {
    return realpathSync(path).startsWith(realpathSync(root) + sep) ? 'ok' : 'outside-root'
  } catch {
    return 'outside-root'
  }
}

// The state of a git operation that rewrites the work tree, per repo (spec R7): the files of a repo in the middle of one are left alone.
const GIT_OPERATION_PATHS = ['MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'BISECT_LOG']

// WHY git rev-parse --git-path and not a look at <top>/.git: in a linked worktree .git is a file and the state lives in the worktree's own git dir, which only git can name. WHY a git failure is its own answer (no write) and not "no operation": a repo whose state cannot be read is not known to be idle. WHY no cache: this runs only for a file about to be written, and a cached answer could be stale by the time a merge starts during a long run.
export function gitOperation(real: string): 'none' | 'operation' | 'failed' {
  const dir = dirname(real)
  const top = findGitTop(dir)
  if (top === null) return 'none'
  if (!top.readable) return 'failed'
  const args = ['-c', 'core.fsmonitor=false', '-C', dir, 'rev-parse']
  for (const name of GIT_OPERATION_PATHS) args.push('--git-path', name)
  const done = spawnSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
  if (done.status !== 0) return 'failed'
  const paths = done.stdout.split('\n').filter((line) => line !== '')
  if (paths.length !== GIT_OPERATION_PATHS.length) return 'failed'
  // The paths are relative to the folder git ran in (-C dir).
  return paths.some((path) => existsSync(resolve(dir, path))) ? 'operation' : 'none'
}

// Temp file in the same folder (so the rename stays on one filesystem), the original mode, fsync, then a re-check of size, mtime and inode against the read, then the rename. WHY the re-check: a file that changed after it was read would lose that change; a re-run picks it up. The window between the re-check and the rename is not closed (stated). Owner, group and extended attributes are not copied.
export function writeAtomic(real: string, bytes: Buffer, before: BigIntStats): 'written' | 'changed-during-redact' | 'write-error' {
  const tmp = join(dirname(real), `.shield-redact-${process.pid}.tmp`)
  let fd: number | null = null
  try {
    fd = openSync(tmp, 'wx', 0o600)
    fchmodSync(fd, Number(before.mode & 0o7777n))
    writeFileSync(fd, bytes)
    fsyncSync(fd)
    closeSync(fd)
    fd = null
    const now = statSync(real, { bigint: true })
    if (now.size !== before.size || now.mtimeNs !== before.mtimeNs || now.ino !== before.ino) {
      unlinkSync(tmp)
      return 'changed-during-redact'
    }
    renameSync(tmp, real)
    return 'written'
  } catch {
    if (fd !== null) closeSync(fd)
    try {
      unlinkSync(tmp)
    } catch {
      // No temp file to remove: the open itself failed.
    }
    return 'write-error'
  }
}
