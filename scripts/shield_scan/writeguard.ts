// secrets-shield redact, write-target guard (TRDD-BAQB9SYO increment 3, step 3a-3a): checked just before a file is replaced.
// WHY: the walker looks at a file with lstat once, when it lists it, and the worker then opens and realpaths the path, both of which follow symlinks. A file that became a symlink (or sits behind a folder that became one) during a long run would have its target rewritten, possibly outside the scanned root. The check runs again at the last moment: the path must still be a regular file, not a symlink, and its real path must lie strictly inside the real path of the scan root.
// The window between this check and the rename is not closed (stated, like the one in writeAtomic).

import { lstatSync, realpathSync } from 'node:fs'
import { sep } from 'node:path'
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
