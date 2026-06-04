"""Tests for scripts/lib/ml_model_patterns.py.

Pattern-coverage tests for the Wave-19 distillation round 5 angle A
catalogue (ML model tampering / supply-chain). Each of the 14 rules
gets at least one positive test and one negative / carve-out test
(plus edge cases where the pattern is subtle).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import ml_model_patterns as mlp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES is a tuple and exposes every advertised rule id."""
    assert isinstance(mlp.RULES, tuple)
    rule_ids = {r.id for r in mlp.RULES}
    expected = {
        "ml-model.torch-load-without-weights-only",
        "ml-model.huggingface-trust-remote-code",
        "ml-model.hf-cache-load-no-digest",
        "ml-model.safetensors-load-untrusted-path",
        "ml-model.onnx-load-no-checker",
        "ml-model.gguf-loader-call-no-size-cap",
        "ml-model.peft-adapter-load-untrusted",
        "ml-model.diffusers-no-revision-pin",
        "ml-model.mlflow-load-no-run-pin",
        "ml-model.wandb-artifact-no-version",
        "ml-model.readme-pip-install-from-git-url",
        "ml-model.tokenizer-special-token-injection",
        "ml-model.shared-cache-dir-writable",
        "ml-model.pipeline-model-name-from-network",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    """Every rule maps to a non-empty ASI- prefix and a known severity."""
    for rule in mlp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the sibling pattern modules' Finding shape."""
    f = mlp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-06"


def test_scan_text_empty_input_returns_empty_list() -> None:
    """scan_text('') returns the empty list (not None / not an error)."""
    assert mlp.scan_text("") == []


def test_scan_text_findings_sorted_by_line_then_col() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        "x = torch.load('a.pt')\n"
        "y = onnx.load('b.onnx')\n"
        "z = AutoModel.from_pretrained('m', trust_remote_code=True)\n"
    )
    out = mlp.scan_text(src)
    # at least one finding from rules 1, 5, 2
    assert len(out) >= 3
    assert out == sorted(out, key=lambda f: (f.line, f.column, f.rule_id))


def _hits(rule_id: str, text: str, *, file_kind: str = "source",
          filename: str = "") -> list[mlp.Finding]:
    return [
        f for f in mlp.scan_text(text, file_kind=file_kind, filename=filename)
        if f.rule_id == rule_id
    ]


# ---------- Rule 1 : torch-load-without-weights-only ---------------------


def test_torch_load_default_call_fires() -> None:
    """`torch.load('file.pt')` with no weights_only kwarg is CRITICAL."""
    src = "state = torch.load('model.pt')\n"
    assert _hits("ml-model.torch-load-without-weights-only", src)


def test_torch_load_with_weights_only_true_suppressed() -> None:
    """`weights_only=True` in the same call is the safe form."""
    src = "state = torch.load('model.pt', weights_only=True)\n"
    assert not _hits("ml-model.torch-load-without-weights-only", src)


def test_torch_load_with_weights_only_false_still_fires() -> None:
    """`weights_only=False` is an explicit unsafe override and must fire."""
    src = "state = torch.load('model.pt', weights_only=False)\n"
    assert _hits("ml-model.torch-load-without-weights-only", src)


def test_torch_load_trusted_checkpoint_pragma_suppresses() -> None:
    """The `# trusted-checkpoint` pragma above is an operator opt-out."""
    src = (
        "# trusted-checkpoint — internal artifact from our build pipeline\n"
        "state = torch.load('model.pt')\n"
    )
    assert not _hits("ml-model.torch-load-without-weights-only", src)


def test_torch_load_in_test_file_is_skipped() -> None:
    """Test harnesses load self-produced checkpoints; suppress by filename."""
    src = "state = torch.load('fixture.pt')\n"
    assert not _hits(
        "ml-model.torch-load-without-weights-only", src,
        filename="tests/test_loader.py",
    )


# ---------- Rule 2 : huggingface-trust-remote-code -----------------------


def test_automodel_trust_remote_code_true_fires() -> None:
    """`AutoModel.from_pretrained(..., trust_remote_code=True)` is CRITICAL."""
    src = "m = AutoModel.from_pretrained('any/repo', trust_remote_code=True)\n"
    assert _hits("ml-model.huggingface-trust-remote-code", src)


def test_pipeline_trust_remote_code_true_fires() -> None:
    """`pipeline(..., trust_remote_code=True)` also fires."""
    src = "p = pipeline('text-generation', model='x', trust_remote_code=True)\n"
    assert _hits("ml-model.huggingface-trust-remote-code", src)


def test_automodelforcausallm_subclass_fires() -> None:
    """The pattern recognises AutoModelForCausalLM and its siblings."""
    src = "m = AutoModelForCausalLM.from_pretrained('x', trust_remote_code=True)\n"
    assert _hits("ml-model.huggingface-trust-remote-code", src)


def test_trust_remote_code_false_does_not_fire() -> None:
    """`trust_remote_code=False` is the safe default — no hit."""
    src = "m = AutoModel.from_pretrained('any/repo', trust_remote_code=False)\n"
    assert not _hits("ml-model.huggingface-trust-remote-code", src)


def test_trust_remote_code_pragma_suppresses() -> None:
    """`# trust-remote-code: <reason>` justifies the override."""
    src = (
        "# trust-remote-code: vetted internal model 2024-Q3\n"
        "m = AutoModel.from_pretrained('x', trust_remote_code=True)\n"
    )
    assert not _hits("ml-model.huggingface-trust-remote-code", src)


# ---------- Rule 3 : hf-cache-load-no-digest -----------------------------


def test_hf_hub_download_then_torch_load_fires() -> None:
    """A download → torch.load with no revision/sha256 anywhere fires."""
    src = (
        "path = hf_hub_download('some/model', 'weights.bin')\n"
        "state = torch.load(path)\n"
    )
    assert _hits("ml-model.hf-cache-load-no-digest", src)


def test_qualified_huggingface_hub_call_fires() -> None:
    """Module-qualified form `huggingface_hub.hf_hub_download` matches too."""
    src = (
        "path = huggingface_hub.hf_hub_download('some/model', 'weights.bin')\n"
        "state = torch.load(path)\n"
    )
    assert _hits("ml-model.hf-cache-load-no-digest", src)


def test_hf_revision_commit_pin_suppresses() -> None:
    """A `revision=<7-40 hex>` commit pin anywhere in the file suppresses."""
    src = (
        "path = hf_hub_download('some/model', 'weights.bin', revision='abc1234')\n"
        "state = torch.load(path)\n"
    )
    assert not _hits("ml-model.hf-cache-load-no-digest", src)


def test_hf_sha256_check_in_file_suppresses() -> None:
    """A sha256 / hashlib reference anywhere in the file means safe."""
    src = (
        "import hashlib\n"
        "path = hf_hub_download('some/model', 'weights.bin')\n"
        "h = hashlib.sha256(open(path,'rb').read()).hexdigest()\n"
        "assert h == EXPECTED\n"
        "state = torch.load(path)\n"
    )
    assert not _hits("ml-model.hf-cache-load-no-digest", src)


def test_hf_pickle_load_also_caught() -> None:
    """`pickle.load(path)` post-download is also a hit (not just torch)."""
    src = (
        "import pickle\n"
        "path = hf_hub_download('x', 'y.pkl')\n"
        "obj = pickle.load(open(path, 'rb'))\n"
    )
    assert _hits("ml-model.hf-cache-load-no-digest", src)


# ---------- Rule 4 : safetensors-load-untrusted-path ---------------------


def test_safetensors_load_from_argv_fires() -> None:
    """safetensors path from `sys.argv[1]` is attacker-controlled."""
    src = "data = safetensors.torch.load_file(sys.argv[1])\n"
    assert _hits("ml-model.safetensors-load-untrusted-path", src)


def test_safetensors_load_from_request_fires() -> None:
    """safetensors path from `request.form['file']` is attacker-controlled."""
    src = "data = safetensors.torch.load_file(request.form['file'])\n"
    assert _hits("ml-model.safetensors-load-untrusted-path", src)


def test_safetensors_load_with_literal_path_does_not_fire() -> None:
    """A literal string path is not attacker-controlled by this rule."""
    src = "data = safetensors.torch.load_file('/opt/models/safe.safetensors')\n"
    assert not _hits("ml-model.safetensors-load-untrusted-path", src)


def test_safetensors_load_from_env_fires() -> None:
    """`os.environ['X']` is attacker-controlled (env-vars are mutable)."""
    src = "data = safetensors.torch.load_file(os.environ['MODEL_PATH'])\n"
    assert _hits("ml-model.safetensors-load-untrusted-path", src)


# ---------- Rule 5 : onnx-load-no-checker --------------------------------


def test_onnx_load_without_checker_fires() -> None:
    """`onnx.load(...)` with no checker.check_model() follow-up fires."""
    src = (
        "model = onnx.load('model.onnx')\n"
        "session = onnxruntime.InferenceSession(model.SerializeToString())\n"
    )
    assert _hits("ml-model.onnx-load-no-checker", src)


def test_onnx_load_with_checker_within_500_chars_suppressed() -> None:
    """A `onnx.checker.check_model(...)` within 500 chars suppresses."""
    src = (
        "model = onnx.load('model.onnx')\n"
        "onnx.checker.check_model(model)\n"
        "session = onnxruntime.InferenceSession(model.SerializeToString())\n"
    )
    assert not _hits("ml-model.onnx-load-no-checker", src)


def test_onnx_unchecked_pragma_suppresses() -> None:
    """`# unchecked-onnx: <reason>` is an explicit opt-out."""
    src = (
        "# unchecked-onnx: validated upstream by IAGA-Sentinel digest receipt\n"
        "model = onnx.load('model.onnx')\n"
    )
    assert not _hits("ml-model.onnx-load-no-checker", src)


# ---------- Rule 6 : gguf-loader-call-no-size-cap ------------------------


def test_llama_loader_with_variable_model_path_fires() -> None:
    """`Llama(model_path=user_path)` is non-literal — fires."""
    src = "llm = Llama(model_path=user_path)\n"
    assert _hits("ml-model.gguf-loader-call-no-size-cap", src)


def test_llama_loader_with_literal_model_path_does_not_fire() -> None:
    """A string-literal model path is trusted-by-shape."""
    src = "llm = Llama(model_path='/opt/models/llama.gguf')\n"
    assert not _hits("ml-model.gguf-loader-call-no-size-cap", src)


def test_gguf_reader_with_variable_filename_fires() -> None:
    """`GGUFReader(filename=p)` is non-literal."""
    src = "rd = GGUFReader(filename=p)\n"
    assert _hits("ml-model.gguf-loader-call-no-size-cap", src)


def test_trusted_gguf_pragma_suppresses() -> None:
    """`# trusted-gguf: <reason>` is an opt-out."""
    src = (
        "# trusted-gguf: vetted llama.gguf shipped via our private registry\n"
        "llm = Llama(model_path=user_path)\n"
    )
    assert not _hits("ml-model.gguf-loader-call-no-size-cap", src)


# ---------- Rule 7 : peft-adapter-load-untrusted -------------------------


def test_peft_model_from_pretrained_fires() -> None:
    """Every `PeftModel.from_pretrained(...)` is flagged for audit."""
    src = "m = PeftModel.from_pretrained(base, 'x/lora-adapter')\n"
    assert _hits("ml-model.peft-adapter-load-untrusted", src)


def test_peft_model_for_causallm_subclass_fires() -> None:
    """`PeftModelForCausalLM.from_pretrained(...)` also fires."""
    src = "m = PeftModelForCausalLM.from_pretrained(base, 'x/adapter')\n"
    assert _hits("ml-model.peft-adapter-load-untrusted", src)


def test_peft_module_qualified_call_fires() -> None:
    """`peft.PeftModel.from_pretrained(...)` qualified form fires."""
    src = "m = peft.PeftModel.from_pretrained(base, 'x/adapter')\n"
    assert _hits("ml-model.peft-adapter-load-untrusted", src)


def test_peft_adapter_pinned_pragma_suppresses() -> None:
    """`# adapter-pinned: <commit-sha>` opts out (operator vouches)."""
    src = (
        "# adapter-pinned: 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b\n"
        "m = PeftModel.from_pretrained(base, 'x/lora')\n"
    )
    assert not _hits("ml-model.peft-adapter-load-untrusted", src)


# ---------- Rule 8 : diffusers-no-revision-pin ---------------------------


def test_stable_diffusion_pipeline_no_revision_fires() -> None:
    """Diffusers pipeline without commit-pinned revision fires."""
    src = "p = StableDiffusionPipeline.from_pretrained('runwayml/sd-v1-5')\n"
    assert _hits("ml-model.diffusers-no-revision-pin", src)


def test_diffusion_pipeline_with_hex_revision_suppressed() -> None:
    """`revision='abc1234'` (7-40 hex) suppresses the hit."""
    src = (
        "p = StableDiffusionPipeline.from_pretrained("
        "'runwayml/sd-v1-5', revision='abc1234')\n"
    )
    assert not _hits("ml-model.diffusers-no-revision-pin", src)


def test_flux_pipeline_no_revision_fires() -> None:
    """FluxPipeline is matched by the diffusers `*Pipeline` family."""
    src = "p = FluxPipeline.from_pretrained('black-forest-labs/flux')\n"
    assert _hits("ml-model.diffusers-no-revision-pin", src)


def test_diffusers_revision_branch_main_still_fires() -> None:
    """`revision='main'` is NOT a commit pin — must still fire."""
    src = (
        "p = StableDiffusionPipeline.from_pretrained("
        "'runwayml/sd-v1-5', revision='main')\n"
    )
    assert _hits("ml-model.diffusers-no-revision-pin", src)


# ---------- Rule 9 : mlflow-load-no-run-pin ------------------------------


def test_mlflow_s3_path_fires() -> None:
    """A raw `s3://` URI is not a run/version pin and fires."""
    src = "m = mlflow.pyfunc.load_model('s3://bucket/models/latest')\n"
    assert _hits("ml-model.mlflow-load-no-run-pin", src)


def test_mlflow_models_stage_alias_fires() -> None:
    """`models:/sentiment/Production` is a stage alias — fires."""
    src = "m = mlflow.pyfunc.load_model('models:/sentiment/Production')\n"
    assert _hits("ml-model.mlflow-load-no-run-pin", src)


def test_mlflow_runs_uri_suppressed() -> None:
    """`runs:/<32-hex>/model` is a real run-id pin — no hit."""
    src = (
        "m = mlflow.pyfunc.load_model("
        "'runs:/00000000000000000000000000000000/model')\n"
    )
    assert not _hits("ml-model.mlflow-load-no-run-pin", src)


def test_mlflow_models_numeric_version_suppressed() -> None:
    """`models:/sentiment/1` is a numeric-version pin — no hit."""
    src = "m = mlflow.pyfunc.load_model('models:/sentiment/1')\n"
    assert not _hits("ml-model.mlflow-load-no-run-pin", src)


def test_mlflow_sklearn_flavor_also_fires() -> None:
    """Rule covers non-pyfunc flavors (sklearn, pytorch, etc.)."""
    src = "m = mlflow.sklearn.load_model('s3://bucket/models/latest')\n"
    assert _hits("ml-model.mlflow-load-no-run-pin", src)


# ---------- Rule 10 : wandb-artifact-no-version --------------------------


def test_wandb_artifact_latest_alias_fires() -> None:
    """`name:latest` is an alias, not a version pin — fires."""
    src = "art = run.use_artifact('sentiment:latest')\n"
    assert _hits("ml-model.wandb-artifact-no-version", src)


def test_wandb_artifact_v3_version_suppressed() -> None:
    """`name:v3` IS a numeric version pin — no hit."""
    src = "art = run.use_artifact('sentiment:v3')\n"
    assert not _hits("ml-model.wandb-artifact-no-version", src)


def test_wandb_artifact_bare_name_fires() -> None:
    """Bare artifact name (no colon) re-resolves and fires."""
    src = "art = run.use_artifact('sentiment')\n"
    assert _hits("ml-model.wandb-artifact-no-version", src)


def test_wandb_api_artifact_alias_fires() -> None:
    """`wandb.Api().artifact(...)` form also catches alias references."""
    src = "art = wandb.Api().artifact('sentiment:production')\n"
    assert _hits("ml-model.wandb-artifact-no-version", src)


def test_wandb_alias_ok_pragma_suppresses() -> None:
    """`# wandb-alias-ok: <reason>` on the same line is an opt-out."""
    src = (
        "art = run.use_artifact('sentiment:latest')  "
        "# wandb-alias-ok: dev loop only\n"
    )
    assert not _hits("ml-model.wandb-artifact-no-version", src)


# ---------- Rule 11 : readme-pip-install-from-git-url --------------------


def test_pip_install_git_in_model_card_fires() -> None:
    """A `pip install git+...` line in a HF model card README fires."""
    src = (
        "---\n"
        "library_name: transformers\n"
        "pipeline_tag: text-generation\n"
        "---\n"
        "# Usage\n"
        "Run `pip install git+https://github.com/example/repo` to install.\n"
    )
    assert _hits(
        "ml-model.readme-pip-install-from-git-url", src,
    )


def test_pip_install_git_in_generic_readme_does_not_fire() -> None:
    """Without HF model-card frontmatter, the rule does not fire."""
    src = "Run `pip install git+https://github.com/example/repo` to install.\n"
    assert not _hits("ml-model.readme-pip-install-from-git-url", src)


def test_pip_install_git_in_model_card_file_kind_fires() -> None:
    """`file_kind='model-card'` forces the rule on (no frontmatter needed)."""
    src = "Run `pip install git+https://github.com/example/repo` to install.\n"
    assert _hits(
        "ml-model.readme-pip-install-from-git-url", src,
        file_kind="model-card",
    )


def test_pip_install_wheel_url_in_model_card_fires() -> None:
    """Raw wheel URL pip-install also fires."""
    src = (
        "---\n"
        "library_name: transformers\n"
        "tags:\n"
        "  - text-generation\n"
        "---\n"
        "pip install https://example.com/foo-0.1.0-py3-none-any.whl\n"
    )
    assert _hits("ml-model.readme-pip-install-from-git-url", src)


def test_pip_install_archive_url_in_model_card_fires() -> None:
    """`https://host/.../archive/...` URL form fires."""
    src = (
        "---\n"
        "library_name: transformers\n"
        "pipeline_tag: text-generation\n"
        "---\n"
        "pip install https://github.com/foo/bar/archive/refs/heads/main.tar.gz\n"
    )
    assert _hits("ml-model.readme-pip-install-from-git-url", src)


def test_do_not_run_disclaimer_suppresses() -> None:
    """`DO NOT RUN` disclaimer above the snippet suppresses the hit."""
    src = (
        "---\n"
        "library_name: transformers\n"
        "pipeline_tag: text-generation\n"
        "---\n"
        "DO NOT RUN — this is for historical reference only.\n"
        "pip install git+https://github.com/legacy/snippet\n"
    )
    assert not _hits("ml-model.readme-pip-install-from-git-url", src)


# ---------- Rule 12 : tokenizer-special-token-injection ------------------


def test_tokenizer_add_tokens_from_request_fires() -> None:
    """`tokenizer.add_tokens([request.form['x']])` is attacker-controlled."""
    src = "tokenizer.add_tokens([request.form['token']])\n"
    assert _hits("ml-model.tokenizer-special-token-injection", src)


def test_tokenizer_add_special_tokens_from_input_fires() -> None:
    """`add_special_tokens` with `input(...)` value also fires."""
    src = "tokenizer.add_special_tokens({'unk_token': input('?')})\n"
    assert _hits("ml-model.tokenizer-special-token-injection", src)


def test_tokenizer_add_tokens_constant_list_does_not_fire() -> None:
    """A literal list of constant strings is not attacker-controlled."""
    src = "tokenizer.add_tokens(['<|im_start|>', '<|im_end|>'])\n"
    assert not _hits("ml-model.tokenizer-special-token-injection", src)


def test_tokenizer_add_tokens_from_env_fires() -> None:
    """`os.environ` value is attacker-controlled (mutable)."""
    src = "tokenizer.add_tokens([os.environ['CUSTOM_TOKEN']])\n"
    assert _hits("ml-model.tokenizer-special-token-injection", src)


# ---------- Rule 13 : shared-cache-dir-writable --------------------------


def test_from_pretrained_with_tmp_cache_fires() -> None:
    """`cache_dir='/tmp/hf-cache'` is shared and writable — fires."""
    src = "m = AutoModel.from_pretrained('x', cache_dir='/tmp/hf-cache')\n"
    assert _hits("ml-model.shared-cache-dir-writable", src)


def test_hf_hub_download_with_dev_shm_cache_fires() -> None:
    """`/dev/shm/` is shared memory — same shared-writable risk."""
    src = (
        "p = hf_hub_download('x', 'w.bin', cache_dir='/dev/shm/my-cache')\n"
    )
    assert _hits("ml-model.shared-cache-dir-writable", src)


def test_from_pretrained_with_private_cache_does_not_fire() -> None:
    """A normal user cache (e.g. `~/.cache/...`) is not in the bad list."""
    src = (
        "m = AutoModel.from_pretrained('x', cache_dir='/home/me/.cache/hf')\n"
    )
    assert not _hits("ml-model.shared-cache-dir-writable", src)


def test_from_pretrained_with_var_tmp_cache_fires() -> None:
    """`/var/tmp/` is also shared and writable."""
    src = "m = AutoModel.from_pretrained('x', cache_dir='/var/tmp/hf')\n"
    assert _hits("ml-model.shared-cache-dir-writable", src)


# ---------- Rule 14 : pipeline-model-name-from-network -------------------


def test_pipeline_model_from_request_json_fires() -> None:
    """`pipeline(model=request.json['name'])` is network-controlled."""
    src = "p = transformers.pipeline(model=request.json['model_name'])\n"
    assert _hits("ml-model.pipeline-model-name-from-network", src)


def test_pipeline_model_from_environ_fires() -> None:
    """`pipeline(model=os.environ['MODEL'])` is env-controlled."""
    src = "p = transformers.pipeline(model=os.environ['MODEL'])\n"
    assert _hits("ml-model.pipeline-model-name-from-network", src)


def test_pipeline_model_from_argv_fires() -> None:
    """`pipeline(model=sys.argv[1])` is CLI-controlled."""
    src = "p = transformers.pipeline(model=sys.argv[1])\n"
    assert _hits("ml-model.pipeline-model-name-from-network", src)


def test_pipeline_model_with_literal_does_not_fire() -> None:
    """A string-literal model name is safe-by-shape."""
    src = "p = transformers.pipeline(model='distilbert-base-uncased')\n"
    assert not _hits("ml-model.pipeline-model-name-from-network", src)


def test_pipeline_model_from_request_body_fires() -> None:
    """`pipeline(model=req.body)` is network-controlled."""
    src = "p = transformers.pipeline(model=req.body)\n"
    assert _hits("ml-model.pipeline-model-name-from-network", src)


# ---------- Integration tests --------------------------------------------


def test_multiple_rules_fire_independently() -> None:
    """A file mixing several distinct bad shapes returns all findings."""
    src = (
        "import torch, onnx, transformers\n"
        "model = torch.load('x.pt')\n"                              # R1
        "m = AutoModel.from_pretrained('y', trust_remote_code=True)\n"  # R2
        "m2 = onnx.load('z.onnx')\n"                                # R5
    )
    out = mlp.scan_text(src)
    rule_ids = {f.rule_id for f in out}
    assert "ml-model.torch-load-without-weights-only" in rule_ids
    assert "ml-model.huggingface-trust-remote-code" in rule_ids
    assert "ml-model.onnx-load-no-checker" in rule_ids


def test_findings_dedup_by_line_col_rule() -> None:
    """No duplicate findings for the same (rule_id, line, col)."""
    src = "x = torch.load('x.pt')  # repeat\nx = torch.load('y.pt')\n"
    out = [f for f in mlp.scan_text(src)
           if f.rule_id == "ml-model.torch-load-without-weights-only"]
    seen = {(f.rule_id, f.line, f.column) for f in out}
    assert len(seen) == len(out)


def test_line_and_col_correctness() -> None:
    """Line / column are 1-based and point at the matched call start."""
    src = "x = 1\ny = torch.load('x.pt')\n"
    out = _hits("ml-model.torch-load-without-weights-only", src)
    assert out
    assert out[0].line == 2
    # `torch.load` starts at column 5 (1-based): "y = torch..."
    assert out[0].column == 5
