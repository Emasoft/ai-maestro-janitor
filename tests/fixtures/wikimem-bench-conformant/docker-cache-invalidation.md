---
name: docker-cache-invalidation
description: "docker build reinstalls dependencies every time / the layer cache never hits / build got slower after adding a file / CI builds take 12 minutes for a one-line change"
ocd: 2026-07-23
lmd: 2026-07-23
metadata:
  node_type: memory
  type: project
  tier: component
---

Why a Dockerfile that looks cached rebuilds from scratch.

^copy-before-install-busts-everything [desc: copying_the_whole_source_before_installing_deps_invalidates_every_later_layer, keywords: docker_build_reinstalls_dependencies_every_time the_layer_cache_never_hits CI_builds_take_12_minutes_for_a_one-line_change npm_install_runs_on_every_build, type: project, ocd: 2026-07-23, lmd: 2026-07-23]
`COPY . .` before the dependency install puts every source file into the cache key of the install
layer, so editing one line invalidates the install and everything after it. Copy only the
manifest (`package.json`, `pyproject.toml`, lockfile), install, then copy the source — the
install layer then depends only on the files that actually determine it.

^mtime-is-not-in-the-cache-key [desc: docker_hashes_content_not_timestamps_so_a_touched_file_does_not_bust_the_cache, keywords: build_got_slower_after_adding_a_file does_touch_invalidate_the_docker_cache why_did_the_cache_miss, type: project, ocd: 2026-07-23, lmd: 2026-07-23]
The cache key is a content hash, not an mtime, so `touch` alone does not cause a miss. A miss
after "no real change" almost always means a generated file (a lockfile, a build stamp, a
coverage report) is inside the build context and genuinely changed content.

^dockerignore-is-part-of-the-key [desc: an_unignored_generated_directory_silently_changes_the_build_context_every_run, keywords: cache_misses_even_though_nothing_changed node_modules_in_the_build_context dockerignore_missing, type: project, ocd: 2026-07-23, lmd: 2026-07-23]
Without a `.dockerignore`, directories like `node_modules/`, `.venv/`, and `target/` enter the
build context. They change on every local run, so the context hash changes and the cache misses
for reasons invisible in the Dockerfile itself.

## Notes and lessons learned

[^1]: [id:ATOM-DOCK-6R1P, status:valid, keywords:"cache_misses_even_though_nothing_changed", ocd:2026-07-23, lmd:2026-07-23] DO NOT conclude the Docker cache is broken when a build misses with no source change, BECAUSE the context hash covers generated files an unignored directory drags in, so the change is real even though it is not yours. DO diff the build context, not the Dockerfile.
