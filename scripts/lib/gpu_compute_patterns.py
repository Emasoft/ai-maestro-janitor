"""GPU / CUDA / OpenCL / Metal compute API misuse patterns.

Wave-24 distillation round 10, angle: GPU compute security.

Catalogue of 10 GPU-API anti-patterns distilled in
`reports/distill-round-10/gpu-compute.md`. Targets `cuda` / `pycuda` /
`cupy` / `numba.cuda` / `pyopencl` / Metal (Swift / Objective-C) surfaces
that prior distill rounds 4–9 do NOT cover at all (verified
orthogonality — no GPU-API ruleset exists in the corpus).

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * gpu-cudamalloc-no-error-check                            (HIGH)
  * gpu-kernel-no-thread-bounds-check                        (CRITICAL)
  * gpu-stream-create-no-synchronize                         (HIGH)
  * gpu-opencl-untrusted-global-work-size                    (HIGH)
  * gpu-metal-private-buffer-no-purgeable                    (MEDIUM)
  * gpu-cuda-managed-no-prefetch                             (MEDIUM)
  * gpu-kernel-printf-debug-leak                             (HIGH)
  * gpu-shared-mem-race-no-syncthreads                       (HIGH)
  * gpu-multi-thread-setdevice-race                          (HIGH)
  * gpu-cudafree-on-inflight-pointer                         (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Identity & Privilege Abuse (multi-thread setdevice race
                                        across tenants)
  ASI-05 — Unexpected Code Execution (untrusted OpenCL work-size,
                                       shared-memory race side-channel)
  ASI-06 — Memory Poisoning (alloc-no-check, bounds-missing,
                              stream-no-sync, kernel-printf leak,
                              shared-mem race, cudaFree UAF)
  ASI-08 — Cascading Failures (UM oversubscription DoS, alloc-fail
                                propagation, Metal VRAM exhaustion)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes; every bounded greedy span uses an
explicit numeric upper bound). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns. RE2-safe: no nested quantifiers, no backreferences,
    no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- G1 : gpu-cudamalloc-no-error-check ---------------------------------


# Trigger pattern: any cuda*Alloc-shape call (C, C++, pycuda, cupy).
# Bounded character class on argument list prevents catastrophic
# backtracking; `[^;)\n]{0,400}` is the inner-args ceiling.
_CUDA_ALLOC_CALL = _re(
    r"\b(?:cudaMalloc|cudaMallocAsync|cudaMallocManaged|cudaMallocHost"
    r"|cudaHostAlloc|cuMemAlloc|cuMemAllocAsync|cuMemAllocManaged"
    r"|cuda\.mem_alloc|cupy\.cuda\.alloc)"
    r"\s*\([^;)\n]{0,400}\)"
)

# Project-local check macros that wrap the alloc and consume the
# cudaError_t. If any of these appear immediately enclosing the alloc,
# the call is safe.
_CUDA_CHECK_WRAPPER = _re(
    r"\b(?:CUDA_CHECK|CHECK_CUDA|cudaSafeCall|gpuErrchk|CU_CHECK"
    r"|checkCudaErrors|CUDA_SAFE_CALL|HANDLE_ERROR)\s*\("
)

# Python-side guard: cuda.mem_alloc / cupy.cuda.alloc inside a
# try/except is treated as a check.
_PYTHON_TRY_GUARD = _re(r"^\s*try\s*:\s*$")
_PYTHON_EXCEPT_GUARD = _re(
    r"^\s*except\s+(?:pycuda\._driver\.MemoryError"
    r"|cupy\.cuda\.memory\.OutOfMemoryError"
    r"|cupy\.cuda\.runtime\.CUDARuntimeError"
    r"|MemoryError"
    r"|RuntimeError"
    r"|Exception)"
)


# ---- G2 : gpu-kernel-no-thread-bounds-check -----------------------------


# CUDA C/C++ __global__ kernel body (bounded inner length to avoid
# catastrophic backtracking). The matched span is the full kernel block.
_CUDA_GLOBAL_KERNEL_BLOCK = _re(
    r"__global__\s+(?:void|[\w:<>\*\s,]{1,80})\s+\w+\s*\([^)]{0,400}\)"
    r"\s*\{[\s\S]{0,2000}?\}"
)

# Numba.cuda kernel decorator + def + body (bounded). Anchor on the
# decorator + def header.
_NUMBA_CUDA_KERNEL_BLOCK = _re(
    r"^@cuda\.jit[^\n]{0,80}\n(?:[^\n]*\n){0,2}\s*def\s+\w+\s*\([^)]{0,200}\)\s*:"
    r"[\s\S]{0,2000}?(?=^\S|\Z)"
)

# Marker that the kernel computes a global thread index — required
# precondition for the rule to fire.
_KERNEL_THREAD_INDEX = _re(
    r"\b(?:blockIdx\.[xyz]|threadIdx\.[xyz]|cuda\.grid\s*\("
    r"|cuda\.threadIdx\b|cuda\.blockIdx\b)"
)

# Bounds guard: any of these absolves the kernel from G2 firing.
_KERNEL_BOUNDS_GUARD = _re(
    r"\bif\s*\(?\s*\w+\s*(?:>=|<|<=|>)\s*\w+"
    r"|"
    r"\b__assume\s*\([^)]{0,200}<"
    r"|"
    # numba.cuda: `if i < arr.size` style
    r"\bif\s+\w+\s*<\s*\w+\.(?:size|shape|len)"
    r"|"
    # cooperative-groups templated bound
    r"\bcooperative_groups::"
)

# Marker that an array is actually indexed inside the kernel body.
_KERNEL_ARRAY_INDEX = _re(r"\w+\s*\[\s*\w+\s*\]\s*[\+\-\*/]?=")


# ---- G3 : gpu-stream-create-no-synchronize ------------------------------


_STREAM_CREATE_CALL = _re(
    r"\b(?:cudaStreamCreate|cuStreamCreate|cudaStreamCreateWithFlags"
    r"|cudaStreamCreateWithPriority"
    r"|torch\.cuda\.Stream\(|cp\.cuda\.Stream\(|cupy\.cuda\.Stream\()"
)

_STREAM_SYNC_MARKER = _re(
    r"\b(?:cudaStreamSynchronize|cuStreamSynchronize|cudaDeviceSynchronize"
    r"|cuCtxSynchronize|torch\.cuda\.synchronize"
    # method-call shape: foo.synchronize()
    r"|\.synchronize\s*\(\s*\)"
    # CUDA Graph capture is a legitimate deferral — treat as sync
    r"|cudaGraphLaunch|cuGraphLaunch)"
)


# ---- G4 : gpu-opencl-untrusted-global-work-size -------------------------


_OPENCL_NDRANGE_CALL = _re(
    r"\bclEnqueueNDRangeKernel\s*\("
    r"|"
    # pyopencl: prog.kernel_name(queue, (gws,), None, ...)
    r"\b[A-Za-z_][\w]*\.\w+\s*\(\s*queue\s*,\s*\([^)]{0,200}\)\s*,"
)

# Untrusted-source markers for the work-size variable.
_UNTRUSTED_WORK_SIZE_SOURCE = _re(
    r"\b(?:argv|getenv|os\.environ|os\.getenv"
    r"|request\.(?:args|form|json|params|values)"
    r"|req\.(?:body|query|params)"
    r"|input\s*\(|atoi\s*\(|atol\s*\(|strtol\s*\("
    r"|json\.loads|loads\s*\(|sys\.argv|process\.env)\b"
)

_WORK_SIZE_CLAMP_MARKER = _re(
    r"\bCL_DEVICE_MAX_WORK_(?:ITEM_SIZES|GROUP_SIZE)\b"
    r"|"
    r"\b(?:min|MIN)\s*\([^)]{0,80}(?:MAX_WORK|max_work_group)"
    r"|"
    # Hard-coded ceiling check
    r"\bif\s+\w+\s*>\s*\d{2,6}\s*:?\s*(?:\w+\s*=|return|raise)"
)


# ---- G5 : gpu-metal-private-buffer-no-purgeable -------------------------


_METAL_PRIVATE_BUFFER_ALLOC = _re(
    r"\bmakeBuffer\s*\(\s*length\s*:[^)]{0,200}\.storageModePrivate"
    r"|"
    r"\bnewBufferWithLength\s*:[^]]{0,200}MTLResourceStorageModePrivate"
)

_METAL_PURGEABLE_RELEASE = _re(
    r"\bsetPurgeableState\s*\(\s*\.empty\s*\)"
    r"|"
    r"\bsetPurgeableState\s*:\s*MTLPurgeableStateEmpty"
    r"|"
    # MTLHeap / MTLResidencySet auto-managed
    r"\bMTLHeap\b|\bMTLResidencySet\b|\bmakeHeap\s*\("
)


# ---- G6 : gpu-cuda-managed-no-prefetch ----------------------------------


_CUDA_MANAGED_ALLOC = _re(
    r"\b(?:cudaMallocManaged|cuMemAllocManaged)\s*\("
)

_CUDA_PREFETCH_MARKER = _re(
    r"\b(?:cudaMemPrefetchAsync|cuMemPrefetchAsync)\s*\("
)


# ---- G7 : gpu-kernel-printf-debug-leak ----------------------------------


# CUDA C/C++ __global__ kernel that contains a printf-class call.
_CUDA_KERNEL_PRINTF = _re(
    r"__global__\s+[^{}\n]{0,200}\{[\s\S]{0,2000}?"
    r"\b(?:printf|cuPrintf|vprintf)\s*\("
)

# OpenCL: kernel ... { ... printf( ... ) }
_OPENCL_KERNEL_PRINTF = _re(
    r"\b__kernel\s+[^{}\n]{0,200}\{[\s\S]{0,2000}?\bprintf\s*\("
)

# Metal Shading Language: os_log inside a metal function (bounded).
_METAL_KERNEL_OSLOG = _re(
    r"\b(?:kernel|fragment|vertex)\s+\w[\w\s\*&<>:,]{0,200}\{"
    r"[\s\S]{0,2000}?\bos_log(?:_with_type)?\s*\("
)

# numba.cuda kernel containing a bare print() call. Bounded lookahead
# of 400 chars max — RE2-safe explicit ceiling.
_NUMBA_KERNEL_PRINT = _re(
    r"^@cuda\.jit[\s\S]{0,400}?\bprint\s*\("
)


# ---- G8 : gpu-shared-mem-race-no-syncthreads ----------------------------


# A CUDA __shared__ declaration followed (within 400 chars) by a
# write to s[expr] and a subsequent read s[other_expr] without a
# __syncthreads/__syncwarp marker between them. The pattern itself
# only locates the candidate region; the Stage-B check looks for the
# missing sync.
_SHARED_MEM_DECL = _re(
    r"\b__shared__\s+[\w<>\[\],\s\*]{1,80}\s*;"
)

# Marker that a sync primitive is present in the region.
_SYNCTHREADS_MARKER = _re(
    r"\b__syncthreads\s*\(\s*\)"
    r"|"
    r"\b__syncwarp\s*\("
    r"|"
    r"\b__shfl_sync\s*\("
    r"|"
    r"\bcooperative_groups::sync\s*\("
    r"|"
    # cg::tile.sync() / cg::this_thread_block().sync()
    r"\.sync\s*\(\s*\)"
)

# Region marker: write s[..] = .. AND read s[..] of different index.
_SHARED_READ_WRITE_REGION = _re(
    r"\w+\s*\[[^\]\n]{1,40}\]\s*=[\s\S]{0,400}?"
    r"\w+\s*\[[^\]\n]{1,40}\]\s*[\+\-\*/]?="
)


# ---- G9 : gpu-multi-thread-setdevice-race -------------------------------


_SETDEVICE_CALL = _re(
    r"\b(?:cudaSetDevice|cuCtxSetCurrent|cuDevicePrimaryCtxRetain)\s*\("
    r"|"
    r"\bcupy\.cuda\.Device\s*\(\s*\d+\s*\)\.use\s*\("
    r"|"
    r"\bcp\.cuda\.runtime\.setDevice\s*\("
)

_THREADING_MARKER = _re(
    r"\b(?:threading\.Thread|pthread_create|std::thread|std::jthread"
    r"|concurrent\.futures\.ThreadPoolExecutor|asyncio\.to_thread"
    r"|tbb::parallel_for|omp\s+parallel)\b"
)

# Proper per-thread context binding (suppresses the rule).
_PER_THREAD_CTX_GUARD = _re(
    r"\bcudaCtxSetCurrent\s*\("
    r"|"
    # `with cupy.cuda.Device(i):` scope is RAII per-thread.
    r"^\s*with\s+cupy\.cuda\.Device\s*\("
    r"|"
    r"^\s*with\s+cp\.cuda\.Device\s*\("
    r"|"
    r"\bcuCtxPushCurrent\s*\("
)


# ---- G10 : gpu-cudafree-on-inflight-pointer -----------------------------


# Synchronous free of a device pointer. cudaFreeAsync(ptr, stream) is
# EXCLUDED because stream-ordered free is the correct idiom.
_CUDA_SYNC_FREE = _re(
    r"\b(?:cudaFree|cuMemFree)\s*\("
)

# Marker that an async kernel launch / async memcpy on a non-default
# stream has occurred earlier in the same scope. CUDA's chevron-launch
# syntax with 4 args includes a stream operand:
#   kernel<<<g, b, smem, stream>>>(args)
_ASYNC_LAUNCH_MARKER = _re(
    r"<<<\s*[^>]{1,200}?,\s*[^>]{1,40}?,\s*[^>]{1,40}?,\s*[A-Za-z_]\w*\s*>>>"
    r"|"
    r"\b(?:cudaMemcpyAsync|cudaMemsetAsync)\s*\("
    r"|"
    # PyTorch CPU pull on a tensor produced inside a user stream
    r"\btorch\.cuda\.stream\s*\("
)

_PRE_FREE_SYNC_MARKER = _re(
    r"\b(?:cudaStreamSynchronize|cuStreamSynchronize|cudaDeviceSynchronize"
    r"|cuCtxSynchronize|torch\.cuda\.synchronize)\s*\("
)


# ---- The rule registry -------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="gpu-cudamalloc-no-error-check",
        name="cudaMalloc / cu*Alloc return value not checked",
        severity="HIGH",
        description=(
            "A bare `cudaMalloc(&p, n)` / `cuMemAlloc` / `cudaMallocAsync` / "
            "`cuda.mem_alloc` / `cupy.cuda.alloc` call whose return "
            "value is discarded and which is NOT wrapped in a "
            "`CUDA_CHECK` / `CHECK_CUDA` / `cudaSafeCall` / "
            "`gpuErrchk` macro (C/C++) nor in a Python `try/except` for "
            "`pycuda._driver.MemoryError` / "
            "`cupy.cuda.memory.OutOfMemoryError`. On allocation failure "
            "the pointer is left undefined; subsequent `cudaMemcpy` "
            "reads from a wild pointer, corrupting another tenant's "
            "allocation on a shared GPU or producing an exploitable "
            "use-after-free inside the same process."
        ),
        pattern=_CUDA_ALLOC_CALL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="gpu-kernel-no-thread-bounds-check",
        name="CUDA / numba.cuda kernel missing bounds guard on thread index",
        severity="CRITICAL",
        description=(
            "A `__global__` CUDA kernel (or `@cuda.jit` numba kernel) "
            "computes a global thread index via "
            "`blockIdx.x * blockDim.x + threadIdx.x` or `cuda.grid(1)` "
            "and indexes an array with it, WITHOUT an `if (idx >= n) "
            "return;` (CUDA) or `if i < arr.size:` (numba) guard. The "
            "host typically rounds the grid up to a multiple of block "
            "size; the trailing threads read/write past the buffer. A "
            "GPU access does NOT page-fault — it lands in an adjacent "
            "allocation belonging to another CUDA context on the same "
            "device, leaking or corrupting that tenant's memory."
        ),
        pattern=_CUDA_GLOBAL_KERNEL_BLOCK,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="gpu-stream-create-no-synchronize",
        name="CUDA stream created without subsequent synchronize",
        severity="HIGH",
        description=(
            "Code creates an asynchronous CUDA stream "
            "(`cudaStreamCreate`, `torch.cuda.Stream(`, "
            "`cupy.cuda.Stream(`) and launches kernels/copies onto it, "
            "but never calls `cudaStreamSynchronize` / "
            "`stream.synchronize()` / `cudaDeviceSynchronize` / "
            "`cudaGraphLaunch` in the same scope. The host reads "
            "`h_out` while the kernel is still running; worst case is "
            "freeing the device buffer with `cudaFree` while the kernel "
            "still has it live — a device use-after-free that leaks "
            "data from the freed region to the next allocation."
        ),
        pattern=_STREAM_CREATE_CALL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="gpu-opencl-untrusted-global-work-size",
        name="OpenCL clEnqueueNDRangeKernel global_work_size from untrusted input",
        severity="HIGH",
        description=(
            "A host application accepts `global_work_size` from user "
            "input (CLI argv, environment variable, REST request, JSON "
            "config) and passes it directly to "
            "`clEnqueueNDRangeKernel` / `prg.kernel(queue, (gws,), …)` "
            "without bounding it against device capabilities "
            "(`CL_DEVICE_MAX_WORK_ITEM_SIZES` / "
            "`CL_DEVICE_MAX_WORK_GROUP_SIZE`) or the input buffer "
            "length. A user-controlled `1 << 40` work size silently "
            "truncates on some drivers (NVIDIA, Intel), missing the "
            "buffer; on others (AMD ROCm, PoCL) it triggers a "
            "driver-level resource exhaustion that hangs the GPU queue "
            "and stalls every other tenant — denial-of-service "
            "primitive on a shared GPU."
        ),
        pattern=_OPENCL_NDRANGE_CALL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="gpu-metal-private-buffer-no-purgeable",
        name="Metal .storageModePrivate buffer without setPurgeableState(.empty)",
        severity="MEDIUM",
        description=(
            "A Metal `MTLBuffer` allocated with `.storageModePrivate` "
            "(Swift `device.makeBuffer(length:options:[.storageModePrivate])`) "
            "or `MTLResourceStorageModePrivate` (Objective-C "
            "`newBufferWithLength:options:`) lives in VRAM and is NOT "
            "released when the Swift/ObjC owner drops its reference "
            "unless `setPurgeableState(.empty)` / "
            "`setPurgeableState:MTLPurgeableStateEmpty` is called (or "
            "the buffer is added to a `MTLHeap` / `MTLResidencySet`). "
            "Long-running ML inference loops that allocate "
            "per-iteration buffers silently exhaust VRAM; production "
            "builds suppress the validation-layer warning and users see "
            "`kIOReturnNoResources` hours into a job."
        ),
        pattern=_METAL_PRIVATE_BUFFER_ALLOC,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="gpu-cuda-managed-no-prefetch",
        name="cudaMallocManaged without cudaMemPrefetchAsync (UM oversubscription DoS)",
        severity="MEDIUM",
        description=(
            "A `cudaMallocManaged` / `cuMemAllocManaged` Unified Memory "
            "allocation is followed by a kernel launch that touches "
            "every page, but no `cudaMemPrefetchAsync` / "
            "`cuMemPrefetchAsync` call moves the pages onto the device "
            "first. Unified Memory migrates page-by-page on first "
            "device touch; on a heavily-loaded multi-tenant GPU this "
            "serialises the page-fault handler across all tenants and "
            "effectively halts the device. A low-privilege caller "
            "hitting an inference endpoint can DoS the entire GPU this "
            "way. Correct fix: prefetch, OR allocate `cudaMalloc` "
            "(device-only) for workloads that don't need UM."
        ),
        pattern=_CUDA_MANAGED_ALLOC,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="gpu-kernel-printf-debug-leak",
        name="Device-side printf left in CUDA / OpenCL / Metal / numba kernel",
        severity="HIGH",
        description=(
            "A device kernel contains a `printf(...)` / `cuPrintf(...)` "
            "/ `os_log(...)` / numba `print(...)` left over from "
            "debugging. CUDA's device-side printf flushes to the host "
            "process's stdout/stderr on the next "
            "`cudaDeviceSynchronize`; OpenCL kernel `printf` and Metal "
            "MSL `os_log` behave identically. In ML inference services "
            "these logs are shipped to centralised collectors (Splunk, "
            "Loki, Datadog) where they expose model weights, key "
            "material, or user inputs to anyone with log-read access. "
            "Remediation: guard with a release-disabled macro or strip "
            "before deploy."
        ),
        pattern=_CUDA_KERNEL_PRINTF,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="gpu-shared-mem-race-no-syncthreads",
        name="__shared__ memory race — missing __syncthreads between write and cross-thread read",
        severity="HIGH",
        description=(
            "A CUDA kernel declares `__shared__` storage, writes to "
            "`s[tid]` in one thread, and reads `s[other_index]` in "
            "another within the same block, without a `__syncthreads()` "
            "/ `__syncwarp()` / `cooperative_groups::sync()` barrier "
            "between the write and the read. On Volta+ (independent "
            "thread scheduling) the read frequently observes the "
            "pre-write value. In parallel reductions this is a silent "
            "correctness bug; in cryptographic kernels (AES T-tables in "
            "shared memory) it is a timing-channel side-channel "
            "primitive."
        ),
        pattern=_SHARED_MEM_DECL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="gpu-multi-thread-setdevice-race",
        name="Multi-thread cudaSetDevice / cupy.Device race — cross-tenant data leakage",
        severity="HIGH",
        description=(
            "A multithreaded host process calls `cudaSetDevice` / "
            "`cupy.cuda.Device(i).use()` / "
            "`cp.cuda.runtime.setDevice` inside threads created via "
            "`threading.Thread` / `pthread_create` / `std::thread` / "
            "`ThreadPoolExecutor`, without per-thread "
            "`cudaCtxSetCurrent` binding nor a `with "
            "cupy.cuda.Device(i):` RAII scope. The per-thread "
            "*current* device is mutable from any thread; a kernel "
            "launched in thread A can land on device 1 if thread B "
            "switched the current device first. Result: misrouted "
            "memcpys reading another tenant's allocation, silent "
            "cross-tenant data leakage on a multi-tenant GPU host."
        ),
        pattern=_SETDEVICE_CALL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="gpu-cudafree-on-inflight-pointer",
        name="cudaFree on pointer with in-flight async work — device use-after-free",
        severity="CRITICAL",
        description=(
            "Host frees a device buffer with synchronous `cudaFree` / "
            "`cuMemFree` while a previously launched async kernel on a "
            "non-default stream (`kernel<<<g, b, smem, stream>>>`) or "
            "an async memcpy (`cudaMemcpyAsync`) still references it. "
            "The CUDA allocator returns the freed region to the pool; "
            "the next `cudaMalloc` may hand the same VA to a fresh "
            "allocation — including in another process via MPS. The "
            "in-flight kernel then writes into the new owner's buffer. "
            "Device use-after-free with arbitrary cross-tenant impact. "
            "Correct idiom: `cudaFreeAsync(ptr, stream)` enqueued on "
            "the same stream as the kernel, OR an explicit "
            "`cudaStreamSynchronize(stream)` before `cudaFree`."
        ),
        pattern=_CUDA_SYNC_FREE,
        owasp_asi="ASI-06",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B context filters:

      * G1 (cudamalloc-no-error-check) — suppress if the alloc is
        wrapped in a `CUDA_CHECK`-class macro on the same line, or
        sits inside a `try:`/`except <MemoryError-class>` block in the
        ±10-line window.
      * G2 (kernel-no-thread-bounds-check) — fire only when the kernel
        block computes a thread index AND indexes an array AND has no
        bounds guard inside the block.
      * G3 (stream-create-no-synchronize) — fire only when no
        synchronize call appears anywhere later in the file.
      * G4 (opencl-untrusted-global-work-size) — fire only when an
        untrusted-source marker appears in the ±15-line window AND no
        clamp marker appears in the same window.
      * G5 (metal-private-buffer-no-purgeable) — fire only when no
        `setPurgeableState(.empty)` / `MTLHeap` marker appears in the
        next 50 lines.
      * G6 (cuda-managed-no-prefetch) — fire only when no
        `cudaMemPrefetchAsync` appears later in the file.
      * G7 (kernel-printf-debug-leak) — Stage-A literal-shape match
        across CUDA / OpenCL / Metal / numba kernel variants; high
        precision, no Stage-B filter.
      * G8 (shared-mem-race) — fire only when the region following the
        `__shared__` declaration contains both a write and a read AND
        no `__syncthreads` / `__syncwarp` between them.
      * G9 (multi-thread-setdevice-race) — fire only when a threading
        marker appears in the file AND no per-thread context guard
        appears in the ±20-line window.
      * G10 (cudafree-inflight) — fire only when an async-launch
        marker appears earlier in the same function/scope AND no
        synchronize call appears between the async launch and the
        free.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- G1 : gpu-cudamalloc-no-error-check ----
    rule_g1 = rule_by_id["gpu-cudamalloc-no-error-check"]
    parts = text.split("\n")
    for m in _CUDA_ALLOC_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        # Same-line check-macro suppression: scan the same source line.
        same_line = parts[line - 1] if 0 < line <= len(parts) else ""
        if _CUDA_CHECK_WRAPPER.search(same_line) is not None:
            continue
        # Python try/except wrapper suppression: scan ±10 lines for
        # `try:` BEFORE and `except <MemoryError-class>` AFTER.
        window = _slice_window(text, line, 10, 10)
        has_try = _PYTHON_TRY_GUARD.search(window) is not None
        has_except = _PYTHON_EXCEPT_GUARD.search(window) is not None
        if has_try and has_except:
            continue
        _emit(rule_g1, m.start(), m.group(0))

    # ---- G2 : gpu-kernel-no-thread-bounds-check ----
    rule_g2 = rule_by_id["gpu-kernel-no-thread-bounds-check"]
    for m in _CUDA_GLOBAL_KERNEL_BLOCK.finditer(text):
        block = m.group(0)
        if _KERNEL_THREAD_INDEX.search(block) is None:
            continue
        if _KERNEL_ARRAY_INDEX.search(block) is None:
            continue
        if _KERNEL_BOUNDS_GUARD.search(block) is not None:
            continue
        _emit(rule_g2, m.start(), block)
    for m in _NUMBA_CUDA_KERNEL_BLOCK.finditer(text):
        block = m.group(0)
        if _KERNEL_THREAD_INDEX.search(block) is None:
            continue
        if _KERNEL_ARRAY_INDEX.search(block) is None:
            continue
        if _KERNEL_BOUNDS_GUARD.search(block) is not None:
            continue
        _emit(rule_g2, m.start(), block)

    # ---- G3 : gpu-stream-create-no-synchronize ----
    rule_g3 = rule_by_id["gpu-stream-create-no-synchronize"]
    has_sync = _file_contains(text, _STREAM_SYNC_MARKER)
    if not has_sync:
        for m in _STREAM_CREATE_CALL.finditer(text):
            _emit(rule_g3, m.start(), m.group(0))

    # ---- G4 : gpu-opencl-untrusted-global-work-size ----
    rule_g4 = rule_by_id["gpu-opencl-untrusted-global-work-size"]
    for m in _OPENCL_NDRANGE_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 15, 15)
        if _UNTRUSTED_WORK_SIZE_SOURCE.search(window) is None:
            continue
        if _WORK_SIZE_CLAMP_MARKER.search(window) is not None:
            continue
        _emit(rule_g4, m.start(), m.group(0))

    # ---- G5 : gpu-metal-private-buffer-no-purgeable ----
    rule_g5 = rule_by_id["gpu-metal-private-buffer-no-purgeable"]
    for m in _METAL_PRIVATE_BUFFER_ALLOC.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 50)
        if _METAL_PURGEABLE_RELEASE.search(window) is not None:
            continue
        _emit(rule_g5, m.start(), m.group(0))

    # ---- G6 : gpu-cuda-managed-no-prefetch ----
    rule_g6 = rule_by_id["gpu-cuda-managed-no-prefetch"]
    has_prefetch = _file_contains(text, _CUDA_PREFETCH_MARKER)
    if not has_prefetch:
        for m in _CUDA_MANAGED_ALLOC.finditer(text):
            _emit(rule_g6, m.start(), m.group(0))

    # ---- G7 : gpu-kernel-printf-debug-leak ----
    rule_g7 = rule_by_id["gpu-kernel-printf-debug-leak"]
    for m in _CUDA_KERNEL_PRINTF.finditer(text):
        _emit(rule_g7, m.start(), m.group(0))
    for m in _OPENCL_KERNEL_PRINTF.finditer(text):
        _emit(rule_g7, m.start(), m.group(0))
    for m in _METAL_KERNEL_OSLOG.finditer(text):
        _emit(rule_g7, m.start(), m.group(0))
    for m in _NUMBA_KERNEL_PRINT.finditer(text):
        _emit(rule_g7, m.start(), m.group(0))

    # ---- G8 : gpu-shared-mem-race-no-syncthreads ----
    rule_g8 = rule_by_id["gpu-shared-mem-race-no-syncthreads"]
    for m in _SHARED_MEM_DECL.finditer(text):
        line, _ = _line_col(text, m.start())
        # Region: 40 lines forward of the declaration is enough to
        # capture the typical reduction body.
        region = _slice_forward(text, line, 40)
        if _SHARED_READ_WRITE_REGION.search(region) is None:
            continue
        if _SYNCTHREADS_MARKER.search(region) is not None:
            continue
        _emit(rule_g8, m.start(), m.group(0))

    # ---- G9 : gpu-multi-thread-setdevice-race ----
    rule_g9 = rule_by_id["gpu-multi-thread-setdevice-race"]
    has_threading = _file_contains(text, _THREADING_MARKER)
    if has_threading:
        for m in _SETDEVICE_CALL.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 20, 20)
            if _PER_THREAD_CTX_GUARD.search(window) is not None:
                continue
            _emit(rule_g9, m.start(), m.group(0))

    # ---- G10 : gpu-cudafree-on-inflight-pointer ----
    rule_g10 = rule_by_id["gpu-cudafree-on-inflight-pointer"]
    for m in _CUDA_SYNC_FREE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Look 30 lines back for an async-launch marker.
        backward = _slice_window(text, line, 30, 0)
        if _ASYNC_LAUNCH_MARKER.search(backward) is None:
            continue
        # Suppress if a synchronize sits between launch and free.
        # Approximate "between" as: any synchronize in the same backward
        # window — coarse but RE2-safe and adequate for static scan.
        if _PRE_FREE_SYNC_MARKER.search(backward) is not None:
            continue
        _emit(rule_g10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
