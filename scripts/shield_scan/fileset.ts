// The file set of the secrets-shield scan (TRDD-BAQB9SYO increment 1a, spec decision D5): which files a scan reads, and the counts of what it did not read and why.
// Default scope: inside a git repo, the files `git ls-files -co --exclude-standard` lists (tracked files, plus untracked files no ignore rule hides); outside a repo, every file. Scope all: every file of the filesystem walk, plus each repo `.git/config` (it can hold a token in a remote URL) and no other `.git` content.

import { spawn } from 'node:child_process'
import { lstatSync, type Stats } from 'node:fs'
import { readdir } from 'node:fs/promises'
import { dirname, join, relative, sep } from 'node:path'

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
  /** Repos found by lstat in the ignored folders of a listed repo (the ignored folder itself or a direct subfolder of it): not scanned in default scope; deeper repos are not counted; always 0 with --all. */
  ignoredRepos: number
  /** True when the root has no .git of its own, sits under an ancestor repo, and is walked plain because that repo lists nothing under it (it ignores every path under the root, or the root is empty). */
  ancestorRulesSkipped: boolean
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
  return { repos: 0, nonRepoDirs: 0, gitignoredEntries: 0, ignoredRepos: 0, ancestorRulesSkipped: false, skipRecords: [], skipped }
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

type GitEntry = 'present' | 'absent' | 'unreadable'

// The one definition of "this folder holds a .git entry": a directory, or a file as in linked worktrees and submodules.
function probeGitEntry(dir: string): GitEntry {
  try {
    lstatSync(join(dir, '.git'))
    return 'present'
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    return code === 'ENOENT' || code === 'ENOTDIR' ? 'absent' : 'unreadable'
  }
}

// WHY an entry that cannot be read counts as present here: the walk then goes through git, which fails visibly as a git-error skip, and never walks the folder as if no repo had a say over it.
function hasGitEntry(dir: string): boolean {
  return probeGitEntry(dir) !== 'absent'
}

/** The nearest folder at or above `start` that holds a .git entry, or null. `readable` is false when the entry could not be read (an lstat error other than a missing entry): the walk still takes that folder as the repo, so git fails visibly (a git-error skip); a caller that must not guess (the findings-path check in scan.ts) stops on it instead. */
export function findGitTop(start: string): { dir: string; readable: boolean } | null {
  for (let dir = start; ; dir = dirname(dir)) {
    const entry = probeGitEntry(dir)
    if (entry !== 'absent') return { dir, readable: entry === 'present' }
    if (dirname(dir) === dir) return null
  }
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

async function* walkRepo(repo: string, opts: SetOptions, stats: SetStats, alreadyListed?: Buffer): AsyncGenerator<FileItem> {
  stats.repos++
  // WHY one listing per root: walkFiles already ran this exact listing as its probe and passes the output in; the owner scans 2 TB, so it is not run twice.
  const listed = alreadyListed ?? (await runGit(repo, ['ls-files', '-co', '--exclude-standard', '-z']))
  const ignored = listed === null ? null : await runGit(repo, ['ls-files', '-oi', '--exclude-standard', '--directory', '-z'])
  if (listed === null || ignored === null) {
    noteSkip(stats, opts.root, repo, 'git-error')
    return
  }
  const ignoredEntries = splitZ(ignored)
  stats.gitignoredEntries += ignoredEntries.length
  // WHY: a record that repos inside ignored folders were not scanned. An ignored folder entry that is itself a repo counts 1; otherwise each direct child that is a repo counts 1 (a clone usually sits one level below an ignored entry, such as vendor/lib). Never deeper, never a file read. The cost was not measured: one readdir per ignored folder entry and one lstat per child. A folder that cannot be listed adds nothing: it is ignored content, not a skip.
  for (const entry of ignoredEntries) {
    if (!entry.endsWith('/')) continue
    const dir = join(repo, entry.slice(0, -1))
    // WHY: git 2.56.0 prints ./ in the ignored-directory listing (probed: .gitignore proj/* above the root proj gives ./, group/, inner/, notes.txt). Without this guard the repo folder would count its own direct children, and a child listed again as inner/ would count twice.
    if (dir === repo) continue
    if (probeGitEntry(dir) === 'present') {
      stats.ignoredRepos++
      continue
    }
    let children: string[]
    try {
      children = await readdir(dir)
    } catch {
      continue
    }
    for (const child of children) if (probeGitEntry(join(dir, child)) === 'present') stats.ignoredRepos++
  }
  // A path can be listed more than once (an unmerged path has one entry per stage).
  for (const entry of new Set(splitZ(listed))) {
    const abs = join(repo, entry.endsWith('/') ? entry.slice(0, -1) : entry)
    // WHY: a guard against a ./ entry in this listing (git 2.56.0 was not seen printing one in ls-files -co, which this loop reads; it does print one in the ignored-directory listing, see the count above); such an entry would walk the repo again as a tree of its own.
    if (abs === repo) continue
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
  let names: string[]
  try {
    names = await readdir(dir)
  } catch {
    noteSkip(stats, opts.root, dir, 'unreadable-dir')
    return
  }
  if (opts.all && names.includes('.git')) stats.repos++
  else stats.nonRepoDirs++
  for (const name of names) {
    const abs = join(dir, name)
    // WHY directory versus file comes from lstat and not from the type the directory listing reports: a filesystem can report no entry type, and its directories would then be treated as files and never walked. lstat also never follows a symlink: a link to a folder is a symlink skip.
    const st = inspect(abs)
    const isDir = typeof st !== 'string' && st.isDirectory()
    if (opts.all && name === '.git') {
      // Scope all reads `.git/config` and nothing else of .git; a `.git` file (a linked worktree or a submodule) is a pointer, not content.
      if (isDir && !opts.exclude.has(join(abs, 'config'))) {
        const config = join(abs, 'config')
        const configStat = inspect(config)
        if (configStat !== 'missing') {
          const item = classify(config, configStat, opts, stats)
          if (item !== null) yield item
        }
      }
      continue
    }
    if (isDir) {
      yield* walkTree(abs, opts, stats)
      continue
    }
    if (opts.exclude.has(abs)) continue
    const item = classify(abs, st, opts, stats)
    if (item !== null) yield item
  }
}

async function* walkTree(dir: string, opts: SetOptions, stats: SetStats): AsyncGenerator<FileItem> {
  if (!opts.all && hasGitEntry(dir)) yield* walkRepo(dir, opts, stats)
  else yield* walkPlain(dir, opts, stats)
}

/** Every file the scan reads, in no particular order; what is not read is counted in `stats` as the walk goes. */
export async function* walkFiles(opts: SetOptions, stats: SetStats): AsyncGenerator<FileItem> {
  if (!opts.all && !hasGitEntry(opts.root)) {
    // WHY: a root with no .git of its own, under an ancestor repo, is listed by that repo (walkRepo) when the ancestor lists anything under the root: then its ignore rules apply. The probe lists tracked and untracked files that are not ignored, so a new untracked subfolder of a project is not walked plain. The ancestor lists nothing when it ignores every path under the root or the root is empty: then the root is the explicit choice of the user and is walked as a folder outside any repo; the repos nested under it keep their own rules. WHY emptiness and failure stay apart: an empty listing (exit 0, no output) is a normal answer and means a plain walk; a git failure (null) is a git-error skip of the root, the run is incomplete, and it is never turned into a walk.
    const top = findGitTop(opts.root)
    if (top !== null) {
      const listed = await runGit(opts.root, ['ls-files', '-co', '--exclude-standard', '-z'])
      if (listed === null) {
        noteSkip(stats, opts.root, opts.root, 'git-error')
        return
      }
      if (listed.length > 0) {
        yield* walkRepo(opts.root, opts, stats, listed)
        return
      }
      // WHY the flag: the only signal in the summary that an ancestor repo's ignore rules did not apply to this root (it is walked plain because that repo lists nothing under it).
      stats.ancestorRulesSkipped = true
    }
  }
  yield* walkTree(opts.root, opts, stats)
}
