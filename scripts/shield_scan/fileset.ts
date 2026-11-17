// The file set of the secrets-shield scan (TRDD-BAQB9SYO increment 1a, spec decision D5): which files a scan reads, and the counts of what it did not read and why.
// Default scope: inside a git repo, the files `git ls-files -co --exclude-standard` lists (tracked files, plus untracked files no ignore rule hides); outside a repo, every file. Scope all: every file of the filesystem walk, plus each repo `.git/config` (it can hold a token in a remote URL) and no other `.git` content.

import { spawn } from 'node:child_process'
import { lstatSync, type Dirent, type Stats } from 'node:fs'
import { readdir } from 'node:fs/promises'
import { join, relative, sep } from 'node:path'

export const SKIP_REASONS = ['binary', 'symlink', 'special', 'missing', 'over-size', 'read-error', 'timeout', 'crash', 'git-error', 'unreadable-dir'] as const
export type SkipReason = (typeof SKIP_REASONS)[number]
// The reasons that get a skip record in the findings file; the others are counted in the summary only.
export const RECORDED_REASONS: ReadonlySet<SkipReason> = new Set<SkipReason>(['timeout', 'read-error', 'over-size', 'crash', 'git-error', 'unreadable-dir'])

export interface SkipRecord {
  path: string
  reason: SkipReason
}

export interface SetStats {
  repos: number
  nonRepoDirs: number
  gitignoredEntries: number
  skipRecords: SkipRecord[]
  skipped: Record<SkipReason, number>
}

export interface FileItem {
  rel: string
  abs: string
  size: number
}

export interface SetOptions {
  /** The real path of the scan root: every path the walk yields is built from it. */
  root: string
  all: boolean
  maxBytes: number
  /** Absolute paths never scanned (the findings file and its temporary file). */
  exclude: ReadonlySet<string>
}

export function newStats(): SetStats {
  const skipped = {} as Record<SkipReason, number>
  for (const reason of SKIP_REASONS) skipped[reason] = 0
  return { repos: 0, nonRepoDirs: 0, gitignoredEntries: 0, skipRecords: [], skipped }
}

export function relOf(root: string, abs: string): string {
  const rel = relative(root, abs)
  return rel === '' ? '.' : rel.split(sep).join('/')
}

export function noteSkip(stats: SetStats, root: string, abs: string, reason: SkipReason): void {
  stats.skipped[reason]++
  if (RECORDED_REASONS.has(reason)) stats.skipRecords.push({ path: relOf(root, abs), reason })
}

// Runs git with no shell. WHY core.fsmonitor=false: the scanner runs git inside repos it did not create, and a repo-configured fsmonitor is a command git would run. WHY stderr is not read: it can name a path, and the scan writes fixed text only.
// Returns the bytes of stdout, or null when git exits non-zero (the caller records a git-error skip; never a fallback walk). A git that cannot be started rejects: scan.ts checks for git before the walk starts.
function runGit(repo: string, args: string[]): Promise<Buffer | null> {
  return new Promise((resolve, reject) => {
    const child = spawn('git', ['-c', 'core.fsmonitor=false', '-C', repo, ...args], { stdio: ['ignore', 'pipe', 'ignore'] })
    const chunks: Buffer[] = []
    child.stdout.on('data', (chunk: Buffer) => chunks.push(chunk))
    child.on('error', reject)
    child.on('close', (code) => resolve(code === 0 ? Buffer.concat(chunks) : null))
  })
}

const splitZ = (data: Buffer): string[] => data.toString('utf8').split('\0').filter((entry) => entry.length > 0)

function inspect(abs: string): Stats | 'missing' | 'error' {
  try {
    return lstatSync(abs)
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'ENOENT' ? 'missing' : 'error'
  }
}

function hasGitEntry(dir: string): boolean {
  return inspect(join(dir, '.git')) !== 'missing'
}

// Classifies one path that is not a directory: a regular file within the size cap becomes an item; every other case is counted. lstat, never stat: a symlink is never followed, and a FIFO, socket or device is never opened.
function classify(abs: string, st: Stats | 'missing' | 'error', opts: SetOptions, stats: SetStats): FileItem | null {
  const skip = (reason: SkipReason): null => {
    noteSkip(stats, opts.root, abs, reason)
    return null
  }
  if (st === 'missing') return skip('missing')
  if (st === 'error') return skip('read-error')
  if (st.isSymbolicLink()) return skip('symlink')
  if (!st.isFile()) return skip('special')
  if (st.size > opts.maxBytes) return skip('over-size')
  return { rel: relOf(opts.root, abs), abs, size: st.size }
}

async function* walkRepo(repo: string, opts: SetOptions, stats: SetStats): AsyncGenerator<FileItem> {
  stats.repos++
  const listed = await runGit(repo, ['ls-files', '-co', '--exclude-standard', '-z'])
  const ignored = listed === null ? null : await runGit(repo, ['ls-files', '-oi', '--exclude-standard', '--directory', '-z'])
  if (listed === null || ignored === null) {
    noteSkip(stats, opts.root, repo, 'git-error')
    return
  }
  stats.gitignoredEntries += splitZ(ignored).length
  // A path can be listed more than once (an unmerged path has one entry per stage).
  for (const entry of new Set(splitZ(listed))) {
    const abs = join(repo, entry.endsWith('/') ? entry.slice(0, -1) : entry)
    if (opts.exclude.has(abs)) continue
    const st = inspect(abs)
    // A directory in the listing is a submodule (gitlink) or an untracked nested repo or linked worktree (listed as a directory entry): it is scanned as a tree of its own, which is a repo of its own when it holds a .git.
    if (typeof st !== 'string' && st.isDirectory()) {
      yield* walkTree(abs, opts, stats)
      continue
    }
    const item = classify(abs, st, opts, stats)
    if (item !== null) yield item
  }
}

async function* walkPlain(dir: string, opts: SetOptions, stats: SetStats): AsyncGenerator<FileItem> {
  let entries: Dirent[]
  try {
    entries = await readdir(dir, { withFileTypes: true })
  } catch {
    noteSkip(stats, opts.root, dir, 'unreadable-dir')
    return
  }
  if (opts.all && entries.some((entry) => entry.name === '.git')) stats.repos++
  else stats.nonRepoDirs++
  for (const entry of entries) {
    const abs = join(dir, entry.name)
    if (opts.all && entry.name === '.git') {
      // Scope all reads `.git/config` and nothing else of .git; a `.git` file (a linked worktree or a submodule) is a pointer, not content.
      if (entry.isDirectory() && !opts.exclude.has(join(abs, 'config'))) {
        const config = join(abs, 'config')
        const st = inspect(config)
        if (st !== 'missing') {
          const item = classify(config, st, opts, stats)
          if (item !== null) yield item
        }
      }
      continue
    }
    if (entry.isDirectory()) {
      yield* walkTree(abs, opts, stats)
      continue
    }
    if (opts.exclude.has(abs)) continue
    const item = classify(abs, inspect(abs), opts, stats)
    if (item !== null) yield item
  }
}

async function* walkTree(dir: string, opts: SetOptions, stats: SetStats): AsyncGenerator<FileItem> {
  if (!opts.all && hasGitEntry(dir)) yield* walkRepo(dir, opts, stats)
  else yield* walkPlain(dir, opts, stats)
}

/** Every file the scan reads, in no particular order; what is not read is counted in `stats` as the walk goes. */
export function walkFiles(opts: SetOptions, stats: SetStats): AsyncGenerator<FileItem> {
  return walkTree(opts.root, opts, stats)
}
