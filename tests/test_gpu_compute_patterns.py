"""Tests for scripts/lib/gpu_compute_patterns.py.

Pattern-coverage tests for the Wave-24 distill-round-10 GPU/CUDA/OpenCL/
Metal compute catalogue (10 net-new anti-patterns). Each rule has one
positive test exercising the canary AND one negative test exercising
the carve-out or context-filter suppression.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import gpu_compute_patterns as gcp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(gcp.RULES, tuple)
    rule_ids = {r.id for r in gcp.RULES}
    expected = {
        "gpu-cudamalloc-no-error-check",
        "gpu-kernel-no-thread-bounds-check",
        "gpu-stream-create-no-synchronize",
        "gpu-opencl-untrusted-global-work-size",
        "gpu-metal-private-buffer-no-purgeable",
        "gpu-cuda-managed-no-prefetch",
        "gpu-kernel-printf-debug-leak",
        "gpu-shared-mem-race-no-syncthreads",
        "gpu-multi-thread-setdevice-race",
        "gpu-cudafree-on-inflight-pointer",
    }
    assert expected == rule_ids
    assert len(gcp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in gcp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = gcp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert gcp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[gcp.Finding]:
    return [f for f in gcp.scan_text(text) if f.rule_id == rule_id]


# ---------- G1 : gpu-cudamalloc-no-error-check ---------------------------


def test_g1_bare_cudamalloc_without_check_flags() -> None:
    """Bare `cudaMalloc(&p, n);` with no enclosing CUDA_CHECK macro fires."""
    src = (
        "void run(int n) {\n"
        "    float *d_buf;\n"
        "    cudaMalloc(&d_buf, n * sizeof(float));\n"
        "    cudaMemcpy(d_buf, h_buf, n*sizeof(float), cudaMemcpyHostToDevice);\n"
        "}\n"
    )
    hits = _hits("gpu-cudamalloc-no-error-check", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g1_cuda_check_macro_suppresses() -> None:
    """`CUDA_CHECK(cudaMalloc(...))` on the same line is the safe idiom."""
    src = (
        "void run(int n) {\n"
        "    float *d_buf;\n"
        "    CUDA_CHECK(cudaMalloc(&d_buf, n * sizeof(float)));\n"
        "}\n"
    )
    assert _hits("gpu-cudamalloc-no-error-check", src) == []


# ---------- G2 : gpu-kernel-no-thread-bounds-check -----------------------


def test_g2_unbounded_cuda_kernel_flags() -> None:
    """A __global__ kernel that indexes arr[idx] without `if (idx < n)` fires."""
    src = (
        "__global__ void scale(float *arr, float s) {\n"
        "    int idx = blockIdx.x * blockDim.x + threadIdx.x;\n"
        "    arr[idx] *= s;\n"
        "}\n"
    )
    hits = _hits("gpu-kernel-no-thread-bounds-check", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_g2_guarded_kernel_does_not_flag() -> None:
    """The same kernel with `if (idx >= n) return;` is safe."""
    src = (
        "__global__ void scale(float *arr, float s, int n) {\n"
        "    int idx = blockIdx.x * blockDim.x + threadIdx.x;\n"
        "    if (idx >= n) return;\n"
        "    arr[idx] *= s;\n"
        "}\n"
    )
    assert _hits("gpu-kernel-no-thread-bounds-check", src) == []


# ---------- G3 : gpu-stream-create-no-synchronize ------------------------


def test_g3_stream_create_without_sync_flags() -> None:
    """`cudaStreamCreate` with no synchronize anywhere in the file fires."""
    src = (
        "void run() {\n"
        "    cudaStream_t s;\n"
        "    cudaStreamCreate(&s);\n"
        "    my_kernel<<<g, b, 0, s>>>(d_in, d_out);\n"
        "    process(h_out);\n"
        "    cudaStreamDestroy(s);\n"
        "}\n"
    )
    hits = _hits("gpu-stream-create-no-synchronize", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g3_stream_with_synchronize_does_not_flag() -> None:
    """Same code with `cudaStreamSynchronize(s)` before the host read passes."""
    src = (
        "void run() {\n"
        "    cudaStream_t s;\n"
        "    cudaStreamCreate(&s);\n"
        "    my_kernel<<<g, b, 0, s>>>(d_in, d_out);\n"
        "    cudaStreamSynchronize(s);\n"
        "    process(h_out);\n"
        "}\n"
    )
    assert _hits("gpu-stream-create-no-synchronize", src) == []


# ---------- G4 : gpu-opencl-untrusted-global-work-size -------------------


def test_g4_envvar_workgroup_size_flags() -> None:
    """`gws = atoi(getenv(...))` followed by `clEnqueueNDRangeKernel` fires."""
    src = (
        "void run(cl_command_queue queue, cl_kernel kernel) {\n"
        "    size_t gws = atoi(getenv(\"WORK_SIZE\"));\n"
        "    clEnqueueNDRangeKernel(queue, kernel, 1, NULL, &gws, NULL, 0, NULL, NULL);\n"
        "}\n"
    )
    hits = _hits("gpu-opencl-untrusted-global-work-size", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g4_clamped_workgroup_size_does_not_flag() -> None:
    """Same flow with a `CL_DEVICE_MAX_WORK_GROUP_SIZE` clamp is safe."""
    src = (
        "void run(cl_command_queue queue, cl_kernel kernel) {\n"
        "    size_t gws = atoi(getenv(\"WORK_SIZE\"));\n"
        "    size_t max_size;\n"
        "    clGetDeviceInfo(dev, CL_DEVICE_MAX_WORK_GROUP_SIZE, sizeof(max_size), &max_size, NULL);\n"
        "    if (gws > max_size) gws = max_size;\n"
        "    clEnqueueNDRangeKernel(queue, kernel, 1, NULL, &gws, NULL, 0, NULL, NULL);\n"
        "}\n"
    )
    assert _hits("gpu-opencl-untrusted-global-work-size", src) == []


# ---------- G5 : gpu-metal-private-buffer-no-purgeable -------------------


def test_g5_private_buffer_no_purgeable_flags() -> None:
    """Metal `.storageModePrivate` allocation with no setPurgeableState fires."""
    src = (
        "for batch in batches {\n"
        "    let buf = device.makeBuffer(length: 1<<20,\n"
        "                                options: [.storageModePrivate])!\n"
        "    encode(buf, batch)\n"
        "    commit()\n"
        "}\n"
    )
    hits = _hits("gpu-metal-private-buffer-no-purgeable", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_g5_purgeable_release_suppresses() -> None:
    """Same allocation with `setPurgeableState(.empty)` is safe."""
    src = (
        "for batch in batches {\n"
        "    let buf = device.makeBuffer(length: 1<<20,\n"
        "                                options: [.storageModePrivate])!\n"
        "    encode(buf, batch)\n"
        "    commit()\n"
        "    buf.setPurgeableState(.empty)\n"
        "}\n"
    )
    assert _hits("gpu-metal-private-buffer-no-purgeable", src) == []


# ---------- G6 : gpu-cuda-managed-no-prefetch ----------------------------


def test_g6_managed_alloc_no_prefetch_flags() -> None:
    """`cudaMallocManaged` with no `cudaMemPrefetchAsync` in the file fires."""
    src = (
        "void run(int n) {\n"
        "    float *p;\n"
        "    cudaMallocManaged(&p, n * sizeof(float));\n"
        "    init_data<<<g, b>>>(p, n);\n"
        "    process<<<g, b>>>(p, n);\n"
        "    cudaDeviceSynchronize();\n"
        "}\n"
    )
    hits = _hits("gpu-cuda-managed-no-prefetch", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_g6_managed_alloc_with_prefetch_does_not_flag() -> None:
    """Same code that calls `cudaMemPrefetchAsync` before the kernel passes."""
    src = (
        "void run(int n) {\n"
        "    float *p;\n"
        "    cudaMallocManaged(&p, n * sizeof(float));\n"
        "    cudaMemPrefetchAsync(p, n * sizeof(float), device, stream);\n"
        "    init_data<<<g, b>>>(p, n);\n"
        "}\n"
    )
    assert _hits("gpu-cuda-managed-no-prefetch", src) == []


# ---------- G7 : gpu-kernel-printf-debug-leak ----------------------------


def test_g7_cuda_kernel_printf_flags() -> None:
    """A __global__ kernel containing `printf(...)` fires the leak rule."""
    src = (
        "__global__ void decrypt(uint8_t *ct, uint8_t *pt, uint8_t *key, int n) {\n"
        "    int idx = blockIdx.x * blockDim.x + threadIdx.x;\n"
        "    if (idx >= n) return;\n"
        "    pt[idx] = ct[idx] ^ key[idx];\n"
        "    printf(\"key[%d]=0x%02x\\n\", idx, key[idx]);\n"
        "}\n"
    )
    hits = _hits("gpu-kernel-printf-debug-leak", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g7_host_printf_does_not_flag() -> None:
    """A host-side `printf` outside any kernel block must not fire."""
    src = (
        "#include <stdio.h>\n"
        "int main() {\n"
        "    printf(\"hello, world\\n\");\n"
        "    return 0;\n"
        "}\n"
    )
    assert _hits("gpu-kernel-printf-debug-leak", src) == []


# ---------- G8 : gpu-shared-mem-race-no-syncthreads ----------------------


def test_g8_shared_race_without_syncthreads_flags() -> None:
    """`__shared__ s[N]` with cross-thread read/write and no __syncthreads fires."""
    src = (
        "__global__ void bad_reduce(float *in, float *out) {\n"
        "    __shared__ float s[256];\n"
        "    int tid = threadIdx.x;\n"
        "    s[tid] = in[blockIdx.x * 256 + tid];\n"
        "    if (tid < 128) s[tid] += s[tid + 128];\n"
        "}\n"
    )
    hits = _hits("gpu-shared-mem-race-no-syncthreads", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g8_syncthreads_present_does_not_flag() -> None:
    """Inserting __syncthreads() between write and read suppresses the rule."""
    src = (
        "__global__ void good_reduce(float *in, float *out) {\n"
        "    __shared__ float s[256];\n"
        "    int tid = threadIdx.x;\n"
        "    s[tid] = in[blockIdx.x * 256 + tid];\n"
        "    __syncthreads();\n"
        "    if (tid < 128) s[tid] += s[tid + 128];\n"
        "    __syncthreads();\n"
        "}\n"
    )
    assert _hits("gpu-shared-mem-race-no-syncthreads", src) == []


# ---------- G9 : gpu-multi-thread-setdevice-race -------------------------


def test_g9_setdevice_in_thread_pool_flags() -> None:
    """`cudaSetDevice` inside a thread without a context guard fires."""
    src = (
        "#include <threading.h>\n"
        "import threading\n"
        "def worker(i):\n"
        "    cudaSetDevice(i)\n"
        "    do_work()\n"
        "for i in range(2):\n"
        "    threading.Thread(target=worker, args=(i,)).start()\n"
    )
    hits = _hits("gpu-multi-thread-setdevice-race", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g9_with_device_scope_does_not_flag() -> None:
    """A `with cupy.cuda.Device(i):` RAII scope suppresses the rule."""
    src = (
        "import threading\n"
        "import cupy\n"
        "def worker(i):\n"
        "    with cupy.cuda.Device(i):\n"
        "        cp.cuda.runtime.setDevice(i)\n"
        "        do_work()\n"
        "threading.Thread(target=worker, args=(0,)).start()\n"
    )
    assert _hits("gpu-multi-thread-setdevice-race", src) == []


# ---------- G10 : gpu-cudafree-on-inflight-pointer -----------------------


def test_g10_sync_free_after_async_launch_flags() -> None:
    """`cudaFree` directly after a stream-launched async kernel fires."""
    src = (
        "void run(float *d_ptr, cudaStream_t stream) {\n"
        "    my_kernel<<<g, b, 0, stream>>>(d_ptr);\n"
        "    cudaFree(d_ptr);\n"
        "}\n"
    )
    hits = _hits("gpu-cudafree-on-inflight-pointer", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_g10_sync_before_free_does_not_flag() -> None:
    """Inserting `cudaStreamSynchronize(stream)` before cudaFree suppresses."""
    src = (
        "void run(float *d_ptr, cudaStream_t stream) {\n"
        "    my_kernel<<<g, b, 0, stream>>>(d_ptr);\n"
        "    cudaStreamSynchronize(stream);\n"
        "    cudaFree(d_ptr);\n"
        "}\n"
    )
    assert _hits("gpu-cudafree-on-inflight-pointer", src) == []
