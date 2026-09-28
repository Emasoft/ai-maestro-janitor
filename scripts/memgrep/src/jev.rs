//! Jev prose scorer (TRDD-JHHD3S4Z commit 1) — the provider module behind `memgrep prose`.
//!
//! Sends memory-atom chunks to a Jev-compatible decision endpoint and gets back a
//! semantic-recall probability (0..=1) per chunk. Three backends (typesafe direct,
//! openrouter proxy, self-hosted gateway), one request shape: N chunks in, N answers out.
//! Reliability is jgrep's: 4 retries with full-jitter backoff honoring `Retry-After`, a 30s
//! per-attempt timeout inside a 15s whole-batch deadline, and a per-run circuit breaker that
//! stops burning requests after 3 consecutive fatal errors. Answers are disk-cached under
//! `~/.cache/memgrep/prose/` keyed on exactly what the prompt sends, so re-scoring an
//! unchanged atom never re-bills. With both a typesafe and an openrouter key in the
//! environment (and no explicit `--api`/`$JEV_API` choice), openrouter stands by as a
//! fallback provider, consulted only on availability/credit failures (TRDD-JHHD3S4Z).

// The `memgrep prose` verb wiring lands in commit 2 — until then every public surface is
// "dead" from the binary's point of view. Silence the false positives; tests still run.
#![allow(dead_code)]

use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

/// One memory atom as Jev sees it. `id` is the caller's atom id (never sent — the wire id is
/// generated per-batch position); `title`/`keywords` are optional surfaces, `text` the full
/// body. The cache key hashes `title + keywords + text`, i.e. everything the prompt would say
/// minus the id.
#[derive(Clone, Debug)]
pub struct ProseChunk {
    pub id: String,
    pub title: Option<String>,
    pub keywords: Option<String>,
    pub text: String,
}

impl ProseChunk {
    /// The full text Jev sees for this chunk — desc + keywords + body. The cache key hashes
    /// exactly this, so it must be the one function that both prompt-builder and cache agree on.
    fn full_text(&self) -> String {
        let mut parts: Vec<&str> = Vec::new();
        if let Some(t) = &self.title
            && !t.is_empty()
        {
            parts.push(t);
        }
        if let Some(k) = &self.keywords
            && !k.is_empty()
        {
            parts.push(k);
        }
        parts.push(&self.text);
        parts.join("\n")
    }
}

/// Error taxonomy — each variant carries the hint a 3am caller needs.
#[derive(Debug)]
pub enum JevError {
    /// The 15s whole-batch deadline (including retries) expired.
    Timeout,
    /// 429 — server said come back later.
    RateLimited { retry_after: Option<Duration> },
    /// 402 — the account is out of credit.
    InsufficientCredits,
    /// 401/403 — bad key or forbidden.
    AuthRejected { status: u16 },
    /// A 200 that did not parse into answers.
    Malformed(String),
    /// Transport failure (DNS, connect, TLS, reset).
    Unreachable(String),
    /// No API key found; names every env var tried.
    NoApiKey { providers_tried: Vec<&'static str> },
    /// The circuit breaker tripped: 3 consecutive fatal errors already happened; this batch
    /// was skipped without a request.
    BreakerOpen,
    /// Gateway backend selected but `JEV_GATEWAY_URL` is unset.
    NoGatewayUrl,
}

impl std::fmt::Display for JevError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            JevError::Timeout => write!(
                f,
                "jev: batch timed out (15s deadline including retries) — endpoint slow or unreachable; try the gateway backend or fewer atoms"
            ),
            JevError::RateLimited { retry_after } => match retry_after {
                Some(d) => write!(
                    f,
                    "jev: rate limited (429) — retry after {:.0}s (honoured automatically where possible)",
                    d.as_secs_f64()
                ),
                None => write!(
                    f,
                    "jev: rate limited (429) — no Retry-After given; backoff retried automatically"
                ),
            },
            JevError::InsufficientCredits => write!(
                f,
                "jev: insufficient credits (402) — top up the account behind this provider's key (see the env var you set), or switch --api"
            ),
            JevError::AuthRejected { status } => write!(
                f,
                "jev: auth rejected (HTTP {status}) — the key is wrong, expired, or lacks access; check the env var for the selected provider"
            ),
            JevError::Malformed(detail) => write!(
                f,
                "jev: malformed 200 response — {detail}; if this persists the backend contract changed, report it"
            ),
            JevError::Unreachable(detail) => write!(
                f,
                "jev: endpoint unreachable — {detail}; check network or the backend URL"
            ),
            JevError::NoApiKey { providers_tried } => write!(
                f,
                "jev: no API key — set one of {} (or $JEV_API / --api to pick a provider explicitly)",
                providers_tried.join(", ")
            ),
            JevError::BreakerOpen => write!(
                f,
                "jev: circuit breaker open — 3 consecutive fatal errors already happened this run; fix the cause (auth/credits) and re-run"
            ),
            JevError::NoGatewayUrl => write!(
                f,
                "jev: gateway backend selected but JEV_GATEWAY_URL is unset — export it (e.g. https://my-host/v1/systemone) or pick another --api"
            ),
        }
    }
}

impl std::error::Error for JevError {}

/// Which backend to talk to.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Provider {
    Typesafe,
    Openrouter,
    Gateway,
}

impl Provider {
    fn from_str(s: &str) -> Option<Provider> {
        match s {
            "typesafe" => Some(Provider::Typesafe),
            "openrouter" => Some(Provider::Openrouter),
            "gateway" => Some(Provider::Gateway),
            _ => None,
        }
    }

    fn default_model(self) -> &'static str {
        match self {
            Provider::Typesafe | Provider::Gateway => "jev-latest",
            Provider::Openrouter => "~typesafe/jev-latest",
        }
    }

    /// The env var carrying this provider's API key.
    fn key_env(self) -> &'static str {
        match self {
            Provider::Typesafe => "TYPESAFE_API_KEY",
            Provider::Openrouter => "OPENROUTER_API_KEY",
            Provider::Gateway => "JEV_GATEWAY_API_KEY",
        }
    }

    /// Lowercase name for stderr notices.
    fn name(self) -> &'static str {
        match self {
            Provider::Typesafe => "typesafe",
            Provider::Openrouter => "openrouter",
            Provider::Gateway => "gateway",
        }
    }
}

/// Env read, the crate idiom: unset OR empty both mean absent.
fn env_opt(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|v| !v.is_empty())
}

/// Resolve which provider to use: explicit `--api` > `$JEV_API` > first key found among env
/// vars (typesafe first — the direct backend is preferred over proxies). `explicit` is the
/// `--api` flag value if the caller passed one.
fn resolve_provider(explicit: Option<&str>) -> Result<Provider, JevError> {
    if let Some(name) = explicit {
        return match Provider::from_str(name) {
            Some(p) => Ok(p),
            None => Err(JevError::Malformed(format!(
                "unknown provider '{name}' — expected typesafe|openrouter|gateway"
            ))),
        };
    }
    if let Some(name) = env_opt("JEV_API") {
        return Provider::from_str(&name).ok_or_else(|| {
            JevError::Malformed(format!(
                "$JEV_API='{name}' is not a provider — expected typesafe|openrouter|gateway"
            ))
        });
    }
    for p in [Provider::Typesafe, Provider::Openrouter, Provider::Gateway] {
        if env_opt(p.key_env()).is_some() {
            return Ok(p);
        }
    }
    Err(JevError::NoApiKey {
        providers_tried: vec!["TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_GATEWAY_API_KEY"],
    })
}

/// Full resolved per-run configuration.
#[derive(Clone, Debug)]
pub struct JevConfig {
    pub provider: Provider,
    pub url: String,
    pub model: String,
    pub api_key: String,
    /// Skip both cache read and cache write.
    pub no_cache: bool,
    /// Standby provider consulted ONLY on availability/credit failures of `provider`
    /// (402/429/5xx/timeout/connection). `None` = single provider, the explicit-choice and
    /// gateway modes; a 200-with-garbage (Malformed) or auth rejection never falls back —
    /// a broken query or wrong key must not double-spend on the second account.
    pub fallback: Option<Provider>,
}

/// One provider's per-run connection settings, derived like `JevConfig` but standalone.
fn provider_config(p: Provider, explicit_model: Option<&str>) -> Result<JevConfig, JevError> {
    let api_key = env_opt(p.key_env()).ok_or_else(|| JevError::NoApiKey {
        providers_tried: vec![p.key_env()],
    })?;
    let url = match p {
        Provider::Typesafe => "https://api.typesafe.ai/v1/systemone".to_string(),
        Provider::Openrouter => "https://openrouter.ai/api/alpha/decisions".to_string(),
        Provider::Gateway => env_opt("JEV_GATEWAY_URL").ok_or(JevError::NoGatewayUrl)?,
    };
    let model = explicit_model
        .map(str::to_string)
        .unwrap_or_else(|| p.default_model().to_string());
    Ok(JevConfig { provider: p, url, model, api_key, no_cache: false, fallback: None })
}

impl JevConfig {
    /// Resolve provider + key + URL + model. Errors name the env var to set.
    ///
    /// When the environment carries BOTH a typesafe and an openrouter key and neither
    /// `--api` nor `$JEV_API` made an explicit choice, typesafe is primary and openrouter
    /// is the fallback (owner directive, TRDD-JHHD3S4Z). GATEWAY mode never participates.
    pub fn resolve(explicit_provider: Option<&str>, explicit_model: Option<&str>) -> Result<JevConfig, JevError> {
        let provider = resolve_provider(explicit_provider)?;
        let mut cfg = provider_config(provider, explicit_model)?;
        let explicit_choice = explicit_provider.is_some() || env_opt("JEV_API").is_some();
        cfg.fallback = if !explicit_choice
            && provider == Provider::Typesafe
            && env_opt(Provider::Openrouter.key_env()).is_some()
        {
            Some(Provider::Openrouter)
        } else {
            None
        };
        Ok(cfg)
    }
}

// ---------------------------------------------------------------------------
// Wire format
// ---------------------------------------------------------------------------

#[derive(serde::Serialize)]
struct WireRequest<'a> {
    model: &'a str,
    state: WireState<'a>,
    questions: serde_json::Map<String, serde_json::Value>,
}

#[derive(serde::Serialize)]
struct WireState<'a> {
    chunks: Vec<WireChunk<'a>>,
}

#[derive(serde::Serialize)]
struct WireChunk<'a> {
    id: String,
    title: Option<&'a str>,
    keywords: Option<&'a str>,
    text: &'a str,
}

/// Build the wire request for one batch. The JSON id is the batch position (`c0`, `c1`, …);
/// the caller's `ProseChunk::id` never crosses the wire.
fn build_request<'a>(model: &'a str, chunks: &'a [ProseChunk], query: &'a str) -> WireRequest<'a> {
    let mut questions = serde_json::Map::new();
    for i in 0..chunks.len() {
        let cid = format!("c{i}");
        questions.insert(
            cid.clone(),
            serde_json::json!({
                "type": "noul",
                "instructions": format!(
                    "Look only at the chunk with id \"{cid}\". Semantic recall: does this memory atom match: {query}? Answer yes/no."
                ),
            }),
        );
    }
    WireRequest {
        model,
        state: WireState {
            chunks: chunks
                .iter()
                .map(|c| WireChunk {
                    id: String::new(), // filled below per position
                    title: c.title.as_deref(),
                    keywords: c.keywords.as_deref(),
                    text: &c.text,
                })
                .collect(),
        },
        questions,
    }
    .with_ids()
}

impl<'a> WireRequest<'a> {
    fn with_ids(mut self) -> Self {
        for (i, chunk) in self.state.chunks.iter_mut().enumerate() {
            chunk.id = format!("c{i}");
        }
        self
    }
}

// Response parsing: `answers` maps wire-id → probability. A probability may arrive as a bare
// number or as an object carrying it.

#[derive(Deserialize)]
struct WireResponse {
    answers: HashMap<String, serde_json::Value>,
    #[serde(default)]
    usage: Option<serde_json::Value>,
    #[serde(default)]
    cost: Option<serde_json::Value>,
    #[serde(default)]
    model: Option<String>,
}

/// Extract the probability from one answer value: bare number or object with a probability
/// field (`probability` / `prob` / `p` / `score`), or the OpenRouter decision shape where the
/// probability rides under the verdict-type key (`{"noul": 0.06, "type": "noul"}`).
fn parse_answer(v: &serde_json::Value) -> Result<f64, String> {
    match v {
        serde_json::Value::Number(n) => n.as_f64().ok_or_else(|| "non-finite number".into()),
        serde_json::Value::Object(map) => {
            for key in ["probability", "prob", "p", "score"] {
                if let Some(serde_json::Value::Number(n)) = map.get(key) {
                    return n.as_f64().ok_or_else(|| format!("non-finite {key}"));
                }
            }
            // OpenRouter decision API: probability keyed by the decision type itself.
            if let Some(serde_json::Value::String(t)) = map.get("type") {
                if let Some(serde_json::Value::Number(n)) = map.get(t.as_str()) {
                    return n.as_f64().ok_or_else(|| format!("non-finite {t}"));
                }
            }
            Err(format!(
                "answer object lacks a probability field (tried probability/prob/p/score and type-keyed): {v}"
            ))
        }
        other => Err(format!("answer is {other}, expected number or object")),
    }
}

fn parse_response(body: &str) -> Result<(Vec<Option<f64>>, WireResponse), String> {
    let wire: WireResponse =
        serde_json::from_str(body).map_err(|e| format!("JSON parse failed: {e}"))?;
    if wire.answers.is_empty() {
        return Err("answers object is empty".into());
    }
    let mut out: Vec<(usize, Option<f64>)> = Vec::new();
    for (id, v) in &wire.answers {
        let idx = id
            .strip_prefix('c')
            .and_then(|n| n.parse::<usize>().ok())
            .ok_or_else(|| format!("answer id '{id}' is not a c<N> position"))?;
        let p = parse_answer(v).map_err(|e| format!("answer '{id}': {e}"))?;
        out.push((idx, Some(p)));
    }
    out.sort_by_key(|(i, _)| *i);
    Ok((out.into_iter().map(|(_, p)| p).collect(), wire))
}

// ---------------------------------------------------------------------------
// Reliability knobs
// ---------------------------------------------------------------------------

/// 4 retries max (5 attempts), full-jitter exponential backoff, `Retry-After` honoured.
const MAX_RETRIES: u32 = 4;
const BASE_BACKOFF: Duration = Duration::from_millis(200);
const ATTEMPT_TIMEOUT: Duration = Duration::from_secs(30);
/// Whole-batch deadline including all retries.
const BATCH_DEADLINE: Duration = Duration::from_secs(15);
/// Aborts after this many consecutive fatal (non-retryable) errors, per run.
const BREAKER_THRESHOLD: usize = 3;
/// Questions per request.
const BATCH_SIZE: usize = 16;
/// Concurrent in-flight requests.
const MAX_CONCURRENCY: usize = 16;

/// Injectable sleep so tests observe backoff without waiting. Production uses `thread::sleep`.
type SleepFn = Box<dyn Fn(Duration) + Send + Sync>;

fn backoff_delay(attempt: u32, retry_after: Option<Duration>) -> Duration {
    // Full jitter over the exponential window: 2^attempt * BASE, capped by Retry-After floor.
    let exp = BASE_BACKOFF.saturating_mul(1u32 << attempt.min(10));
    let jittered = Duration::from_secs_f64(rand_f64() * exp.as_secs_f64());
    match retry_after {
        Some(ra) => jittered.max(ra),
        None => jittered,
    }
}

/// Tiny xorshift pseudo-random for jitter — no rand dep for one multiply.
fn rand_f64() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let mut x = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos() as u64 ^ (d.as_secs() << 20))
        .unwrap_or(0x9E3779B97F4A7C15)
        | 1;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    (x % 1_000_000) as f64 / 1_000_000.0
}

fn is_retryable(status: u16) -> bool {
    status == 429 || status >= 500
}

/// Classify one HTTP outcome into retry-or-fatal + the error it becomes when retries exhaust.
enum Outcome {
    Success(Vec<Option<f64>>, Option<serde_json::Value>, Option<serde_json::Value>),
    Retry { retry_after: Option<Duration>, status: u16 },
    Fatal(JevError),
}

// ---------------------------------------------------------------------------
// Circuit breaker (per-run)
// ---------------------------------------------------------------------------

#[derive(Debug, Default)]
struct Breaker {
    consecutive_fatal: AtomicUsize,
    /// At least one recorded fatal was availability-class (402/429/5xx/timeout/connection).
    /// BreakerOpen slots may only fall back when this is set — an open breaker caused by
    /// auth rejections must not silently re-issue against the second account.
    availability_fatal: std::sync::atomic::AtomicBool,
}

impl Breaker {
    fn is_open(&self) -> bool {
        self.consecutive_fatal.load(Ordering::SeqCst) >= BREAKER_THRESHOLD
    }
    fn record_success(&self) {
        self.consecutive_fatal.store(0, Ordering::SeqCst);
    }
    fn record_fatal(&self, e: &JevError) {
        self.consecutive_fatal.fetch_add(1, Ordering::SeqCst);
        if is_fallback_class(e) {
            self.availability_fatal
                .store(true, Ordering::SeqCst);
        }
    }
    fn opened_by_availability(&self) -> bool {
        self.availability_fatal.load(Ordering::SeqCst)
    }
}

// ---------------------------------------------------------------------------
// Disk cache
// ---------------------------------------------------------------------------

/// Cache dir: `$XDG_CACHE_HOME/memgrep/prose` or `~/.cache/memgrep/prose`.
fn cache_dir() -> Option<std::path::PathBuf> {
    let base = env_opt("XDG_CACHE_HOME")
        .or_else(|| env_opt("HOME").map(|h| format!("{h}/.cache")))?;
    Some(std::path::Path::new(&base).join("memgrep").join("prose"))
}

/// sha256 of `normalized_query + sha256(full_chunk_text)` — key hashes exactly what the prompt
/// sends minus the chunk id. Normalization: trim, collapse internal whitespace runs to one
/// space, case-fold.
fn cache_key(provider: Provider, model: &str, query: &str, chunk: &ProseChunk) -> String {
    fn normalize(s: &str) -> String {
        s.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
    }
    let qhash = Sha256::digest(normalize(query).as_bytes());
    let thash = Sha256::digest(chunk.full_text().as_bytes());
    let mut h = Sha256::new();
    h.update(normalize(query).as_bytes());
    h.update(qhash.as_slice());
    h.update(thash.as_slice());
    h.update(model.as_bytes());
    h.update(provider.key_env().as_bytes());
    let digest = h.finalize();
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    hex
}

/// Read the append-only JSONL cache: `{"key": "<hex>", "p": <f64>}` per line.
fn cache_load_all(dir: &std::path::Path) -> HashMap<String, f64> {
    let mut map = HashMap::new();
    let Ok(mut file) = std::fs::File::open(dir.join("answers.jsonl")) else {
        return map;
    };
    let mut buf = String::new();
    use std::io::Read;
    let _ = file.read_to_string(&mut buf);
    for line in buf.lines() {
        let Ok(v) = serde_json::from_str::<serde_json::Value>(line) else {
            continue;
        };
        if let (Some(k), Some(p)) = (v.get("key").and_then(|x| x.as_str()), v.get("p").and_then(|x| x.as_f64())) {
            map.insert(k.to_string(), p);
        }
    }
    map
}

fn cache_append(dir: &std::path::Path, entries: &[(String, f64)]) {
    if entries.is_empty() {
        return;
    }
    if let Err(e) = std::fs::create_dir_all(dir) {
        // Cache is best-effort: a read-only cache dir must never fail a scoring run.
        eprintln!("jev: cache write skipped ({e})");
        return;
    }
    use std::io::Write;
    let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("answers.jsonl"))
    else {
        return;
    };
    for (k, p) in entries {
        let line = serde_json::json!({ "key": k, "p": p });
        let _ = writeln!(f, "{line}");
    }
}

// ---------------------------------------------------------------------------
// The scorer
// ---------------------------------------------------------------------------

/// The test seam: score a query against chunks, one probability or error per chunk, in input
/// order.
pub trait ProseScorer {
    fn score(&self, query: &str, chunks: &[ProseChunk]) -> Vec<Result<f64, JevError>>;
}

/// Per-atom result slots shared between the batch threads and the collector.
type SharedResults = Arc<Mutex<Vec<Option<Result<f64, JevError>>>>>;

pub struct JevScorer {
    pub config: JevConfig,
    breaker: Arc<Breaker>,
    sleep: Mutex<Arc<SleepFn>>,
    cache_dir_override: Option<std::path::PathBuf>,
}

impl JevScorer {
    pub fn new(config: JevConfig) -> JevScorer {
        JevScorer {
            config,
            breaker: Arc::new(Breaker::default()),
            sleep: Mutex::new(Arc::new(Box::new(|d: Duration| thread::sleep(d)))),
            cache_dir_override: None,
        }
    }

    /// Replace the sleep fn (tests pass a no-op that records the durations it was asked for).
    fn set_sleep(&self, f: Arc<SleepFn>) {
        *self.sleep.lock().unwrap() = f;
    }

    /// Point the cache somewhere else (tests use a temp dir).
    fn set_cache_dir(&mut self, dir: std::path::PathBuf) {
        self.cache_dir_override = Some(dir);
    }

    fn effective_cache_dir(&self) -> Option<std::path::PathBuf> {
        self.cache_dir_override.clone().or_else(cache_dir)
    }
}

impl ProseScorer for JevScorer {
    fn score(&self, query: &str, chunks: &[ProseChunk]) -> Vec<Result<f64, JevError>> {
        let primary = self.score_pass(self.config.clone(), Arc::clone(&self.breaker), query, chunks);
        // Fallback chain (owner directive, TRDD-JHHD3S4Z): re-issue only the chunks that
        // failed with a provider-availability/credit error against the standby provider.
        let Some(fb_provider) = self.config.fallback else {
            return primary;
        };
        let retry_slots: Vec<usize> = primary
            .iter()
            .enumerate()
            .filter(|(_, r)| match r {
                Ok(_) => false,
                // BreakerOpen slots fall back only when the breaker was opened BY an
                // availability error — a breaker tripped by 401s must not re-spend.
                Err(JevError::BreakerOpen) => self.breaker.opened_by_availability(),
                Err(e) => is_fallback_class(e),
            })
            .map(|(i, _)| i)
            .collect();
        if retry_slots.is_empty() {
            return primary;
        }
        let Ok(mut fb_cfg) = provider_config(fb_provider, Some(&self.config.model)) else {
            // Standby key vanished mid-run — surface the primary errors untouched.
            return primary;
        };
        // The fallback leg obeys the caller's cache decision: --no-cache must cover BOTH
        // providers, and the fallback leg must never read answers the primary declined to
        // consult (provider_config defaults no_cache to false — re-derive, then inherit).
        fb_cfg.no_cache = self.config.no_cache;
        eprintln!(
            "jev: {} unavailable ({} chunks affected) — retrying against {}",
            self.config.provider.name(),
            retry_slots.len(),
            fb_provider.name()
        );
        // Fresh breaker: the primary pass may have tripped the shared one (availability
        // fatals are exactly what gets us here), and the fallback endpoint's health is
        // independent — it must not inherit the primary's open circuit.
        let fb_results = self.score_pass(
            fb_cfg,
            Arc::new(Breaker::default()),
            query,
            &fb_chunks_vec(chunks, &retry_slots),
        );
        let mut out = primary;
        for (slot, res) in retry_slots.into_iter().zip(fb_results) {
            out[slot] = res;
        }
        out
    }
}

/// The subset of `chunks` at `slots`, in slot order.
fn fb_chunks_vec(chunks: &[ProseChunk], slots: &[usize]) -> Vec<ProseChunk> {
    slots.iter().map(|&i| chunks[i].clone()).collect()
}

impl JevScorer {
    /// One full scoring pipeline against ONE provider config: cache lookup, breaker gate,
    /// batching, concurrent retrying requests, cache writeback. `score` chains this across
    /// the primary and the fallback provider; this method never looks at `config.fallback`.
    fn score_pass(
        &self,
        config: JevConfig,
        breaker: Arc<Breaker>,
        query: &str,
        chunks: &[ProseChunk],
    ) -> Vec<Result<f64, JevError>> {
        if chunks.is_empty() {
            return Vec::new();
        }
        // -------- cache pass --------
        let mut cache: HashMap<String, f64> = HashMap::new();
        let dir = if config.no_cache {
            None
        } else {
            self.effective_cache_dir()
        };
        if let Some(d) = &dir {
            cache = cache_load_all(d);
        }
        let mut results: Vec<Option<Result<f64, JevError>>> = (0..chunks.len()).map(|_| None).collect();
        // Pending atoms as (atom index, chunk, precomputed cache key) — the key rides along so
        // the cache append after scoring uses the exact key the earlier lookup computed.
        let mut pending: Vec<(usize, ProseChunk, String)> = Vec::new();
        for (i, c) in chunks.iter().enumerate() {
            let key = cache_key(config.provider, &config.model, query, c);
            match cache.get(&key) {
                Some(p) => results[i] = Some(Ok(*p)),
                None => pending.push((i, c.clone(), key)),
            }
        }
        let all_cached = pending.is_empty();

        // -------- breaker gate --------
        if breaker.is_open() && !all_cached {
            return results
                .into_iter()
                .map(|r| {
                    r.unwrap_or(Err(JevError::BreakerOpen))
                })
                .collect();
        }

        // -------- batch the pending --------
        let mut batches: Vec<Vec<(usize, ProseChunk, String)>> = Vec::new();
        let mut cur: Vec<(usize, ProseChunk, String)> = Vec::new();
        for item in pending {
            cur.push(item);
            if cur.len() == BATCH_SIZE {
                batches.push(std::mem::take(&mut cur));
            }
        }
        if !cur.is_empty() {
            batches.push(cur);
        }

        // -------- concurrent execution --------
        let deadline = Instant::now() + BATCH_DEADLINE;
        let writebacks: SharedResults = Arc::new(Mutex::new(
            (0..chunks.len()).map(|_| None).collect(),
        ));
        let successes: Arc<Mutex<Vec<(String, f64)>>> = Arc::new(Mutex::new(Vec::new()));
        let totals: Arc<Mutex<(u64, u64, u64)>> = Arc::new(Mutex::new((0, 0, 0))); // prompts, in/out tokens-ish, cost-millis

        let config = Arc::new(config);
        let sleep_fn = self.sleep.lock().unwrap().clone();
        let query = query.to_string();

        // Up to MAX_CONCURRENCY batches in flight via scoped threads.
        thread::scope(|s| {
            let mut handles = Vec::new();
            for (batch_no, batch) in batches.iter().enumerate() {
                if batch_no >= MAX_CONCURRENCY {
                    // Serialized overflow lane: run in-line to keep this sync and simple.
                    // ponytail: >16 batches run serially; parallelize with a work-stealing pool if scoring 256+ atoms is routine.
                    let r = run_batch(
                        &config, &breaker, &sleep_fn, &query, batch, deadline, &totals,
                    );
                    apply_batch(&r, batch, &writebacks, &successes);
                    continue;
                }
                let cfg = config.clone();
                let brk = breaker.clone();
                let slp = sleep_fn.clone();
                let q = query.clone();
                let b = batch.clone();
                let wb = writebacks.clone();
                let ok = successes.clone();
                let tot = totals.clone();
                handles.push(s.spawn(move || {
                    let r = run_batch(&cfg, &brk, &slp, &q, &b, deadline, &tot);
                    apply_batch(&r, &b, &wb, &ok);
                }));
            }
            for h in handles {
                let _ = h.join();
            }
        });

        let mut final_results = {
            let wb = writebacks.lock().unwrap();
            (0..wb.len())
                .map(|i| wb[i].as_ref().map(|r| r.as_ref().map(|p| *p).map_err(clone_error)))
                .collect::<Vec<_>>()
        };

        // Merge cache-only results back: cached slots were recorded pre-breaker into
        // `results`, which we overwrote — restore them for slots the network never touched.
        // (Simpler: recompute from cache; the cache map is already loaded.)
        for (i, c) in chunks.iter().enumerate() {
            if final_results[i].is_some() {
                continue;
            }
            let key = cache_key(config.provider, &config.model, &query, c);
            if let Some(p) = cache.get(&key) {
                final_results[i] = Some(Ok(*p));
            }
        }

        // Persist cache misses that succeeded.
        if let Some(d) = &dir {
            let ok = successes.lock().unwrap().clone();
            cache_append(d, &ok);
        }

        final_results
            .into_iter()
            .map(|r| r.unwrap_or_else(|| Err(JevError::Malformed("unassigned result slot".into()))))
            .collect()
    }
}

/// Apply one batch's outcome to the shared result slots and success list. Each batch item is
/// `(atom index, chunk, cache_key)` — the key is precomputed so the appended cache line stores
/// exactly the key a later lookup will ask for (never the atom id).
fn apply_batch(
    outcome: &Outcome,
    batch: &[(usize, ProseChunk, String)],
    writebacks: &SharedResults,
    successes: &Mutex<Vec<(String, f64)>>,
) {
    let mut wb = writebacks.lock().unwrap();
    match outcome {
        Outcome::Success(probs, _usage, _cost) => {
            let mut ok = successes.lock().unwrap();
            for (slot, (idx, _chunk, key)) in batch.iter().enumerate() {
                let p = probs.get(slot).copied().flatten();
                wb[*idx] = Some(match p {
                    Some(p) => {
                        ok.push((key.clone(), p));
                        Ok(p)
                    }
                    None => Err(JevError::Malformed(format!(
                        "answer for position {slot} missing"
                    ))),
                });
            }
        }
        Outcome::Fatal(e) => {
            for (idx, _, _) in batch {
                wb[*idx] = Some(Err(clone_error(e)));
            }
        }
        _ => {
            // Retry lane exhausted without resolution — unreachable via run_batch (it never
            // returns Retry), defensive only.
            for (idx, _, _) in batch {
                wb[*idx] = Some(Err(JevError::Unreachable("retry loop exited unresolved".into())));
            }
        }
    }
}

/// JevError is not Clone (carries a Vec of strs — fine to rebuild); deep-copy via Display round
/// trip is overkill, so enumerate.
fn clone_error(e: &JevError) -> JevError {
    match e {
        JevError::Timeout => JevError::Timeout,
        JevError::RateLimited { retry_after } => JevError::RateLimited { retry_after: *retry_after },
        JevError::InsufficientCredits => JevError::InsufficientCredits,
        JevError::AuthRejected { status } => JevError::AuthRejected { status: *status },
        JevError::Malformed(d) => JevError::Malformed(d.clone()),
        JevError::Unreachable(d) => JevError::Unreachable(d.clone()),
        JevError::NoApiKey { providers_tried } => JevError::NoApiKey {
            providers_tried: providers_tried.clone(),
        },
        JevError::BreakerOpen => JevError::BreakerOpen,
        JevError::NoGatewayUrl => JevError::NoGatewayUrl,
    }
}

/// Run one batch with retries. Returns the final Outcome (never `Retry` — retries are
/// internal).
fn run_batch(
    config: &JevConfig,
    breaker: &Breaker,
    sleep_fn: &SleepFn,
    query: &str,
    batch: &[(usize, ProseChunk, String)],
    deadline: Instant,
    _totals: &Mutex<(u64, u64, u64)>,
) -> Outcome {
    // Breaker check at batch start: skip without a request.
    if breaker.is_open() {
        return Outcome::Fatal(JevError::BreakerOpen);
    }
    let chunks: Vec<ProseChunk> = batch.iter().map(|(_, c, _)| c.clone()).collect();
    let req = build_request(&config.model, &chunks, query);
    let body = match serde_json::to_string(&req) {
        Ok(b) => b,
        Err(e) => return Outcome::Fatal(JevError::Malformed(format!("serialize request: {e}"))),
    };

    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(10))
        .build();
    let mut last: Option<Outcome> = None;
    for attempt in 0..=MAX_RETRIES {
        if Instant::now() >= deadline {
            return Outcome::Fatal(JevError::Timeout);
        }
        let response = agent
            .post(&config.url)
            .set("Authorization", &format!("Bearer {}", config.api_key))
            .set("Content-Type", "application/json")
            .set("X-Title", "memgrep")
            .timeout(ATTEMPT_TIMEOUT)
            .send_string(&body);

        match response {
            Ok(resp) => {
                let text = match resp.into_string() {
                    Ok(t) => t,
                    Err(_) => {
                        return fatal_breaker(breaker, JevError::Malformed("body read failed".into()));
                    }
                };
                match parse_response(&text) {
                    Ok((probs, _wire)) => {
                        breaker.record_success();
                        return Outcome::Success(probs, _wire.usage, _wire.cost);
                    }
                    Err(detail) => {
                        // Malformed 200 is fatal — the endpoint answered but not in contract.
                        return fatal_breaker(breaker, JevError::Malformed(detail));
                    }
                }
            }
            Err(ureq::Error::Status(code, resp)) => {
                let retry_after = resp
                    .header("retry-after")
                    .and_then(|v| v.trim().parse::<u64>().ok())
                    .map(Duration::from_secs);
                if is_retryable(code) {
                    if code == 429 {
                        last = Some(Outcome::Retry { retry_after, status: code });
                    }
                    if attempt < MAX_RETRIES {
                        let d = backoff_delay(attempt, retry_after);
                        if Instant::now() + d < deadline {
                            sleep_fn(d);
                            continue;
                        }
                    }
                    return match code {
                        429 => Outcome::Fatal(JevError::RateLimited { retry_after }),
                        _ => Outcome::Fatal(JevError::Unreachable(format!(
                            "HTTP {code} after {MAX_RETRIES} retries"
                        ))),
                    };
                }
                // Fatal status.
                let err = match code {
                    402 => JevError::InsufficientCredits,
                    401 | 403 => JevError::AuthRejected { status: code },
                    _ => JevError::Unreachable(format!("HTTP {code}")),
                };
                return fatal_breaker(breaker, err);
            }
            Err(ureq::Error::Transport(t)) => {
                // Transport errors are retryable (jgrep treats network flake as retry).
                if attempt < MAX_RETRIES {
                    let d = backoff_delay(attempt, None);
                    if Instant::now() + d < deadline {
                        sleep_fn(d);
                        continue;
                    }
                }
                return Outcome::Fatal(JevError::Unreachable(format!("transport: {t}")));
            }
        }
    }
    last.unwrap_or_else(|| Outcome::Fatal(JevError::Unreachable("retry loop ended".into())))
}

/// Record a fatal error on the breaker and wrap it.
fn fatal_breaker(breaker: &Breaker, e: JevError) -> Outcome {
    breaker.record_fatal(&e);
    Outcome::Fatal(e)
}

/// Does this failure mean the PROVIDER is unavailable or out of credit — the only class the
/// fallback chain may act on? Malformed (a 200 that did not parse) and auth rejections are
/// NOT fallback-class: a broken query or a wrong key is the caller's problem, and re-issuing
/// it against a second paid account just double-spends (card constraint, TRDD-JHHD3S4Z).
fn is_fallback_class(e: &JevError) -> bool {
    matches!(
        e,
        JevError::InsufficientCredits      // 402
            | JevError::RateLimited { .. } // 429 after retries
            | JevError::Timeout            // batch deadline expired
            | JevError::Unreachable(_)     // 5xx after retries, connect/DNS/TLS, connection refused
    )
}

/// The stderr line the verb prints before scoring — privacy/cost notice.
pub fn privacy_notice(atom_count: usize, provider: Provider) -> String {
    let backend = match provider {
        Provider::Typesafe => "typesafe",
        Provider::Openrouter => "openrouter",
        Provider::Gateway => "gateway",
    };
    format!("[prose] sending {atom_count} atoms to {backend}")
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    // Env-var manipulation races across test threads — serialize every test in this module.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    // Poison-proof: a test that panicked while holding ENV_LOCK must not fail every later
    // test with PoisonError — the env state it left is unknown but each test sets/unsets its
    // own keys, so recovering the inner guard is safe.
    fn env_lock() -> std::sync::MutexGuard<'static, ()> {
        ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner())
    }

    // `std::env::set_var`/`remove_var` are `unsafe` in edition 2024 (they are UB-adjacent under
    // concurrent reads). Every call below happens under ENV_LOCK, the serialization the crate's
    // own single-threaded env reads rely on here.
    fn set_env(k: &str, v: &str) {
        // SAFETY: caller holds ENV_LOCK; no other thread in this test process touches `k`.
        unsafe { std::env::set_var(k, v) }
    }
    fn unset_env(k: &str) {
        // SAFETY: caller holds ENV_LOCK; no other thread in this test process touches `k`.
        unsafe { std::env::remove_var(k) }
    }

    fn chunk(id: &str, text: &str) -> ProseChunk {
        ProseChunk { id: id.into(), title: None, keywords: None, text: text.into() }
    }

    // ---- request shape ----

    #[test]
    fn request_json_has_exact_fields_and_ids() {
        let chunks = vec![chunk("atom-a", "first body"), chunk("atom-b", "second body")];
        let req = build_request("jev-latest", &chunks, "does it rain");
        let v = serde_json::to_value(&req).unwrap();
        assert_eq!(v["model"], "jev-latest");
        assert_eq!(v["state"]["chunks"][0]["id"], "c0");
        assert_eq!(v["state"]["chunks"][1]["id"], "c1");
        assert_eq!(v["state"]["chunks"][0]["text"], "first body");
        assert_eq!(v["questions"]["c0"]["type"], "noul");
        let instr = v["questions"]["c0"]["instructions"].as_str().unwrap();
        assert!(instr.contains("chunk with id \"c0\""));
        assert!(instr.contains("does it rain"));
        assert!(v["questions"]["c1"]["instructions"].as_str().unwrap().contains("\"c1\""));
    }

    // ---- response parse ----

    #[test]
    fn parse_bare_number_answer() {
        let (probs, _) = parse_response(r#"{"answers":{"c0":0.95}}"#).unwrap();
        assert_eq!(probs[0], Some(0.95));
    }

    #[test]
    fn parse_object_with_probability_answer() {
        let (probs, _) = parse_response(
            r#"{"answers":{"c0":{"probability":0.5},"c1":{"p":0.25},"c2":{"score":0.75}}}"#,
        )
        .unwrap();
        assert_eq!(probs[0], Some(0.5));
        assert_eq!(probs[1], Some(0.25));
        assert_eq!(probs[2], Some(0.75));
    }

    #[test]
    fn malformed_200_is_error() {
        assert!(parse_response(r#"{"nope":1}"#).is_err());
        assert!(parse_response(r#"{"answers":{}}"#).is_err());
        assert!(parse_response(r#"{"answers":{"c0":"yes"}}"#).is_err());
        assert!(parse_response("not json").is_err());
    }

    // ---- retry + retry-after ----

    #[test]
    fn retry_429_then_success() {
        let _env = env_lock();
        // Server: 429 (with Retry-After) on first hit, 200 after.
        let hits = Arc::new(AtomicUsize::new(0));
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let h2 = hits.clone();
        let server = thread::spawn(move || {
            for stream in listener.incoming() {
                let mut s = stream.unwrap();
                h2.fetch_add(1, Ordering::SeqCst);
                let mut buf = [0u8; 8192];
                let _ = s.read(&mut buf);
                if h2.load(Ordering::SeqCst) == 1 {
                    let _ = s.write_all(
                        b"HTTP/1.1 429 Too Many Requests\r\nRetry-After: 0\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    );
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
                } else {
                    let _ = s.write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"answers\":{\"c0\":0.9}}",
                    );
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
                }
                let _ = s.flush();
            }
        });
        let cfg = JevConfig {
            provider: Provider::Gateway,
            url: format!("http://127.0.0.1:{port}/v1/systemone"),
            model: "m".into(),
            api_key: "k".into(),
            no_cache: true,
            fallback: None,
        };
        let scorer = JevScorer::new(cfg);
        // Zero backoff so the test is instant; still exercises the retry path.
        let slept: Arc<Mutex<Vec<Duration>>> = Arc::new(Mutex::new(Vec::new()));
        let slept2 = slept.clone();
        scorer.set_sleep(Arc::new(Box::new(move |d| slept2.lock().unwrap().push(d))));
        let out = ProseScorer::score(&scorer, "rain", &[chunk("a", "body")]);
        assert_eq!(out[0].as_ref().unwrap(), &0.9);
        assert_eq!(hits.load(Ordering::SeqCst), 2, "one retry after 429");
        assert!(!slept.lock().unwrap().is_empty(), "backoff was slept");
        drop(server);
    }

    // ---- cache ----

    #[test]
    fn cache_hit_skips_network() {
        let _env = env_lock();
        let tmp = std::env::temp_dir().join(format!("memgrep-jev-cache-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        let cfg = JevConfig {
            provider: Provider::Typesafe,
            url: "http://127.0.0.1:1/unreachable".into(),
            model: "jev-latest".into(),
            api_key: "k".into(),
            no_cache: false,
            fallback: None,
        };
        let mut scorer = JevScorer::new(cfg);
        scorer.set_cache_dir(tmp.clone());
        // Prime the cache: a server that answers once.
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            for stream in listener.incoming().take(1) {
                let mut s = stream.unwrap();
                let mut buf = [0u8; 8192];
                let _ = s.read(&mut buf);
                let _ = s.write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"answers\":{\"c0\":0.42}}",
                );
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
            }
        });
        // Point at the live server for the priming call.
        scorer.config.url = format!("http://127.0.0.1:{port}/v1/systemone");
        let c = chunk("a", "stable body text");
        let first = ProseScorer::score(&scorer, "rain query", &[c.clone()]);
        assert_eq!(first[0].as_ref().unwrap(), &0.42);
        server.join().unwrap();

        // Second call: the URL is now dead — only the cache can answer.
        scorer.config.url = "http://127.0.0.1:1/unreachable".into();
        let second = ProseScorer::score(&scorer, "rain query", &[c]);
        assert_eq!(second[0].as_ref().unwrap(), &0.42, "cache hit without network");
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn no_cache_skips_read_and_write() {
        let _env = env_lock();
        let tmp = std::env::temp_dir().join(format!("memgrep-jev-nocache-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        let mut scorer = JevScorer::new(JevConfig {
            provider: Provider::Typesafe,
            url: "http://127.0.0.1:1/unreachable".into(),
            model: "m".into(),
            api_key: "k".into(),
            no_cache: true,
            fallback: None,
        });
        scorer.set_cache_dir(tmp.clone());
        let out = ProseScorer::score(&scorer, "q", &[chunk("a", "b")]);
        assert!(matches!(out[0], Err(JevError::Unreachable(_))), "no network, no cache, hard error");
        assert!(!tmp.join("answers.jsonl").exists(), "no cache file written");
        let _ = std::fs::remove_dir_all(&tmp);
    }

    // ---- breaker ----

    #[test]
    fn breaker_trips_after_three_consecutive_fatals() {
        let _env = env_lock();
        let hits = Arc::new(AtomicUsize::new(0));
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let h2 = hits.clone();
        let server = thread::spawn(move || {
            for stream in listener.incoming() {
                let mut s = stream.unwrap();
                h2.fetch_add(1, Ordering::SeqCst);
                let mut buf = [0u8; 8192];
                let _ = s.read(&mut buf);
                let _ = s.write_all(
                    b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                );
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
            }
        });
        let scorer = JevScorer::new(JevConfig {
            provider: Provider::Gateway,
            url: format!("http://127.0.0.1:{port}/v1/systemone"),
            model: "m".into(),
            api_key: "k".into(),
            no_cache: true,
            fallback: None,
        });
        scorer.set_sleep(Arc::new(Box::new(|_| {})));
        // 3 batches of 1 atom each → 3 consecutive 401s → breaker opens.
        for i in 0..3 {
            let out = ProseScorer::score(&scorer, "q", &[chunk(&format!("a{i}"), "b")]);
            assert!(out[0].is_err(), "batch {i} should fail with 401");
        }
        assert_eq!(hits.load(Ordering::SeqCst), 3);
        // 4th call: breaker open — zero further requests, BreakerOpen error.
        let before = hits.load(Ordering::SeqCst);
        let out = ProseScorer::score(&scorer, "q", &[chunk("a3", "b")]);
        assert!(matches!(out[0], Err(JevError::BreakerOpen)));
        assert_eq!(hits.load(Ordering::SeqCst), before, "no request after breaker opened");
        drop(server);
    }

    // ---- key precedence ----

    #[test]
    fn explicit_flag_beats_env() {
        let _env = env_lock();
        set_env("TYPESAFE_API_KEY", "ts-key");
        set_env("JEV_API", "openrouter");
        let p = resolve_provider(Some("gateway")).unwrap();
        assert_eq!(p, Provider::Gateway, "--api flag wins over $JEV_API");
        unset_env("TYPESAFE_API_KEY");
        unset_env("JEV_API");
    }

    #[test]
    fn jenv_api_env_selects_provider() {
        let _env = env_lock();
        set_env("OPENROUTER_API_KEY", "or-key");
        set_env("JEV_API", "openrouter");
        let p = resolve_provider(None).unwrap();
        assert_eq!(p, Provider::Openrouter);
        unset_env("OPENROUTER_API_KEY");
        unset_env("JEV_API");
    }

    #[test]
    fn first_env_key_found_typesafe_first() {
        let _env = env_lock();
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("OPENROUTER_API_KEY", "or");
        let p = resolve_provider(None).unwrap();
        assert_eq!(p, Provider::Typesafe);
        unset_env("TYPESAFE_API_KEY");
        unset_env("OPENROUTER_API_KEY");
    }

    #[test]
    fn missing_key_names_env_vars() {
        let _env = env_lock();
        for k in ["TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_GATEWAY_API_KEY", "JEV_API"] {
            unset_env(k);
        }
        let err = resolve_provider(None).unwrap_err();
        match err {
            JevError::NoApiKey { providers_tried } => {
                assert_eq!(providers_tried.len(), 3);
            }
            other => panic!("expected NoApiKey, got {other:?}"),
        }
    }

    #[test]
    fn gateway_without_url_errors() {
        let _env = env_lock();
        set_env("JEV_GATEWAY_API_KEY", "gk");
        unset_env("JEV_GATEWAY_URL");
        let err = JevConfig::resolve(Some("gateway"), None).unwrap_err();
        assert!(matches!(err, JevError::NoGatewayUrl));
        unset_env("JEV_GATEWAY_API_KEY");
    }

    // ---- batch isolation ----

    #[test]
    fn failing_batch_isolates_its_chunks() {
        let _env = env_lock();
        // One batch answers, one 401s — chunks from the good batch still score.
        let hits = Arc::new(AtomicUsize::new(0));
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let h2 = hits.clone();
        let server = thread::spawn(move || {
            let mut n = 0u32;
            for stream in listener.incoming() {
                let mut s = stream.unwrap();
                let mut buf = [0u8; 65536];
                let _ = s.read(&mut buf);
                n += 1;
                h2.fetch_add(1, Ordering::SeqCst);
                if n == 1 {
                    // First request succeeds (whatever batch it is — we isolate by position below).
                    let _ = s.write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"answers\":{\"c0\":0.1,\"c1\":0.2,\"c2\":0.3,\"c3\":0.4,\"c4\":0.5,\"c5\":0.6,\"c6\":0.7,\"c7\":0.8,\"c8\":0.9,\"c9\":1.0,\"c10\":0.11,\"c11\":0.12,\"c12\":0.13,\"c13\":0.14,\"c14\":0.15,\"c15\":0.16}}",
                    );
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
                } else {
                    let _ = s.write_all(
                        b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    );
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
                }
            }
        });
        let scorer = JevScorer::new(JevConfig {
            provider: Provider::Gateway,
            url: format!("http://127.0.0.1:{port}/v1/systemone"),
            model: "m".into(),
            api_key: "k".into(),
            no_cache: true,
            fallback: None,
        });
        scorer.set_sleep(Arc::new(Box::new(|_| {})));
        let chunks: Vec<ProseChunk> = (0..32).map(|i| chunk(&format!("a{i}"), &format!("body {i}"))).collect();
        let out = ProseScorer::score(&scorer, "q", &chunks);
        let oks = out.iter().filter(|r| r.is_ok()).count();
        let errs = out.iter().filter(|r| r.is_err()).count();
        assert_eq!(oks + errs, 32, "every chunk gets an outcome");
        assert!(oks >= 16 && errs >= 16, "a failing batch isolates: got {oks} ok / {errs} err");
        drop(server);
    }

    // ---- mock server through gateway (end-to-end) ----

    #[test]
    fn end_to_end_via_mock_gateway() {
        let _env = env_lock();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            for stream in listener.incoming().take(1) {
                let mut s = stream.unwrap();
                // Read the WHOLE request before asserting: one read may return only the
                // headers with the body still in flight, and a mid-request assert both
                // fails spuriously and kills the connection → client sees connect-refused
                // on its retry (observed ~1 in 10 runs).
                let mut buf = Vec::new();
                let mut take = [0u8; 4096];
                loop {
                    match s.read(&mut take) {
                        Ok(0) | Err(_) => break,
                        Ok(n) => {
                            buf.extend_from_slice(&take[..n]);
                            if String::from_utf8_lossy(&buf).contains("\"model\":\"m\"") {
                                break;
                            }
                        }
                    }
                }
                let req = String::from_utf8_lossy(&buf).to_string();
                assert!(req.contains("Authorization: Bearer test-key"));
                assert!(req.contains("X-Title: memgrep"));
                let body_start = req.find("\r\n\r\n").map(|i| i + 4).unwrap_or(0);
                let body = &req[body_start..];
                assert!(body.contains("\"model\":\"m\""));
                let _ = s.write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"answers\":{\"c0\":0.95,\"c1\":0.05}}",
                );
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
            }
        });
        let scorer = JevScorer::new(JevConfig {
            provider: Provider::Gateway,
            url: format!("http://127.0.0.1:{port}/v1/systemone"),
            model: "m".into(),
            api_key: "test-key".into(),
            no_cache: true,
            fallback: None,
        });
        let out = ProseScorer::score(&scorer, "q", &[chunk("a", "one"), chunk("b", "two")]);
        assert_eq!(out[0].as_ref().unwrap(), &0.95);
        assert_eq!(out[1].as_ref().unwrap(), &0.05);
        server.join().unwrap();
    }

    // ---- timeout: unreachable host fatals as Unreachable (transport), not Timeout ----

    #[test]
    fn unreachable_host_is_transport_error() {
        let _env = env_lock();
        // Port 1 on localhost is closed → connection refused immediately.
        let scorer = JevScorer::new(JevConfig {
            provider: Provider::Gateway,
            url: "http://127.0.0.1:1/v1/systemone".into(),
            model: "m".into(),
            api_key: "k".into(),
            no_cache: true,
            fallback: None,
        });
        scorer.set_sleep(Arc::new(Box::new(|_| {})));
        let out = ProseScorer::score(&scorer, "q", &[chunk("a", "b")]);
        assert!(matches!(out[0], Err(JevError::Unreachable(_))));
    }

    // ---- fallback chain (owner directive, TRDD-JHHD3S4Z) ----

    /// Start a mock provider server answering `status` on every request; returns (port, join).
    fn mock_provider(status_line: &'static str, body: &'static str) -> (u16, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            for stream in listener.incoming() {
                let mut s = stream.unwrap();
                let mut buf = [0u8; 8192];
                let _ = s.read(&mut buf);
                let resp = format!(
                    "HTTP/1.1 {status_line}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{body}"
                );
                let _ = s.write_all(resp.as_bytes());
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
            }
        });
        (port, server)
    }

    #[test]
    fn chain_preferred_typesafe_when_both_keys_present() {
        let _env = env_lock();
        unset_env("JEV_API");
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("OPENROUTER_API_KEY", "or");
        let cfg = JevConfig::resolve(None, None).unwrap();
        assert_eq!(cfg.provider, Provider::Typesafe);
        assert_eq!(cfg.fallback, Some(Provider::Openrouter));
        unset_env("TYPESAFE_API_KEY");
        unset_env("OPENROUTER_API_KEY");
    }

    #[test]
    fn chain_disabled_when_explicit_api_env_set() {
        let _env = env_lock();
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("OPENROUTER_API_KEY", "or");
        set_env("JEV_API", "openrouter");
        let cfg = JevConfig::resolve(None, None).unwrap();
        assert_eq!(cfg.provider, Provider::Openrouter);
        assert_eq!(cfg.fallback, None, "$JEV_API explicit choice → no silent fallback");
        unset_env("TYPESAFE_API_KEY");
        unset_env("OPENROUTER_API_KEY");
        unset_env("JEV_API");
    }

    #[test]
    fn chain_disabled_when_explicit_flag_set() {
        let _env = env_lock();
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("OPENROUTER_API_KEY", "or");
        let cfg = JevConfig::resolve(Some("typesafe"), None).unwrap();
        assert_eq!(cfg.provider, Provider::Typesafe);
        assert_eq!(cfg.fallback, None, "--api explicit choice → no silent fallback");
        unset_env("TYPESAFE_API_KEY");
        unset_env("OPENROUTER_API_KEY");
    }

    #[test]
    fn openrouter_only_env_has_no_fallback() {
        let _env = env_lock();
        unset_env("TYPESAFE_API_KEY");
        unset_env("JEV_GATEWAY_API_KEY");
        set_env("OPENROUTER_API_KEY", "or");
        let cfg = JevConfig::resolve(None, None).unwrap();
        assert_eq!(cfg.provider, Provider::Openrouter);
        assert_eq!(cfg.fallback, None, "openrouter-only keeps working exactly as today");
        unset_env("OPENROUTER_API_KEY");
    }

    #[test]
    fn fallback_does_not_fire_on_malformed_answer() {
        let _env = env_lock();
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("OPENROUTER_API_KEY", "or");
        // Primary answers 200 with garbage; a fallback would need a second server — run none:
        // if the chain fired on Malformed, the chunk would flip to Unreachable (openrouter's
        // real URL), which the assertion catches.
        let (port, server) = mock_provider("200 OK", r#"{"answers":{"c0":"garbage"}}"#);
        let scorer = {
            let mut cfg = provider_config(Provider::Typesafe, None).unwrap();
            cfg.url = format!("http://127.0.0.1:{port}/v1/systemone");
            cfg.no_cache = true;
            cfg.fallback = Some(Provider::Openrouter);
            JevScorer::new(cfg)
        };
        let out = ProseScorer::score(&scorer, "q", &[chunk("a", "b")]);
        assert!(
            matches!(out[0], Err(JevError::Malformed(_))),
            "malformed stays malformed, got {:?}",
            out[0]
        );
        drop(server);
        unset_env("TYPESAFE_API_KEY");
        unset_env("OPENROUTER_API_KEY");
    }

    #[test]
    fn fallback_fires_on_402_and_fallback_auth_error_surfaces() {
        let _env = env_lock();
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("OPENROUTER_API_KEY", "or");
        // Primary: 402 (credit exhausted) → fallback-class → chain fires. Fallback: here a
        // local mock that 401s (no real openrouter) — the FALLBACK's own error surfaces.
        let (p1, s1) = mock_provider("402 Payment Required", "");
        let (p2, s2) = mock_provider("401 Unauthorized", "");
        // The fallback leg re-derives its config from OPENROUTER_API_KEY via provider_config,
        // whose URL is hardcoded to openrouter.ai. To hit the local mock, temporarily resolve
        // the chain by hand instead: build the primary with fallback=None, run score, then
        // run the fallback leg explicitly against p2 — asserting exactly the semantics
        // `score` implements (same helpers, same filter).
        let mut cfg = provider_config(Provider::Typesafe, None).unwrap();
        cfg.url = format!("http://127.0.0.1:{p1}/v1/systemone");
        cfg.no_cache = true;
        cfg.fallback = None;
        let scorer = JevScorer::new(cfg);
        scorer.set_sleep(Arc::new(Box::new(|_| {})));
        let primary = ProseScorer::score(&scorer, "q", &[chunk("a", "b")]);
        assert!(
            matches!(primary[0], Err(JevError::InsufficientCredits)),
            "402 is the primary's error"
        );
        // The chain's filter would select this slot (is_fallback_class(InsufficientCredits)).
        assert!(is_fallback_class(primary[0].as_ref().unwrap_err()));
        // Fallback leg against the mock: 401 is NOT fallback-class and is what surfaces.
        let mut fb = provider_config(Provider::Openrouter, None).unwrap();
        fb.url = format!("http://127.0.0.1:{p2}/v1/systemone");
        fb.no_cache = true;
        let scorer2 = JevScorer::new(fb);
        scorer2.set_sleep(Arc::new(Box::new(|_| {})));
        let second = ProseScorer::score(&scorer2, "q", &[chunk("a", "b")]);
        assert!(matches!(second[0], Err(JevError::AuthRejected { status: 401 })));
        // And the chain would have written that into the slot: filter passes only
        // fallback-class primaries; the fb result replaces it verbatim.
        drop(s1);
        drop(s2);
        unset_env("TYPESAFE_API_KEY");
        unset_env("OPENROUTER_API_KEY");
    }

    #[test]
    fn fallback_completes_on_openrouter_mock_when_typesafe_402s() {
        let _env = env_lock();
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("OPENROUTER_API_KEY", "or");
        // Full end-to-end chain with BOTH legs local: primary (typesafe pose) 402s, the
        // fallback leg re-derives openrouter's URL from provider_config — hardcoded
        // openrouter.ai — so we prove the chain mechanics against the real `score` by
        // pinning the fallback URL the same way production does: provider_config is env-
        // derived, hence this test drives `score` with a scorer whose config.fallback is
        // armed and whose fallback provider_config we cannot redirect. Instead we assert the
        // chain-completion semantics on a scorer where the PRIMARY poses as typesafe
        // (mock 402) and the fallback provider is GATEWAY — the same code path (one
        // provider_config + one score_pass), no production URL touched.
        let (p1, s1) = mock_provider("402 Payment Required", "");
        let (p2, s2) = mock_provider("200 OK", r#"{"answers":{"c0":0.66}}"#);
        set_env("JEV_GATEWAY_API_KEY", "gk");
        set_env("JEV_GATEWAY_URL", &format!("http://127.0.0.1:{p2}/v1/systemone"));
        let mut cfg = provider_config(Provider::Typesafe, None).unwrap();
        cfg.url = format!("http://127.0.0.1:{p1}/v1/systemone");
        cfg.no_cache = true;
        cfg.fallback = Some(Provider::Gateway);
        let scorer = JevScorer::new(cfg);
        scorer.set_sleep(Arc::new(Box::new(|_| {})));
        let out = ProseScorer::score(&scorer, "q", &[chunk("a", "b")]);
        assert_eq!(out[0].as_ref().unwrap(), &0.66, "fallback completed the chunk");
        drop(s1);
        drop(s2);
        unset_env("TYPESAFE_API_KEY");
        unset_env("OPENROUTER_API_KEY");
        unset_env("JEV_GATEWAY_API_KEY");
        unset_env("JEV_GATEWAY_URL");
    }

    #[test]
    fn fallback_leg_gets_fresh_breaker() {
        let _env = env_lock();
        // Primary breaker trips on 3 consecutive 402s (3 batches of 1); the 4th call's
        // fallback leg must still reach its (healthy) mock, not inherit the open breaker.
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("JEV_GATEWAY_API_KEY", "gk");
        set_env("JEV_GATEWAY_URL", "http://127.0.0.1:1/v1/systemone");
        let (p1, s1) = mock_provider("402 Payment Required", "");
        let mut cfg = provider_config(Provider::Typesafe, None).unwrap();
        cfg.url = format!("http://127.0.0.1:{p1}/v1/systemone");
        cfg.no_cache = true;
        cfg.fallback = Some(Provider::Gateway);
        let scorer = JevScorer::new(cfg);
        scorer.set_sleep(Arc::new(Box::new(|_| {})));
        for i in 0..3 {
            let out = ProseScorer::score(&scorer, "q", &[chunk(&format!("a{i}"), "b")]);
            // Each pass: primary 402 → fallback to a dead gateway → Unreachable surfaces.
            assert!(matches!(out[0], Err(JevError::Unreachable(_))), "pass {i}: {:?})", out[0]);
        }
        // Breaker now open AND opened by availability errors. 4th call: primary slots come
        // back BreakerOpen, the chain re-runs them against the (dead) fallback — the
        // surfaced error is the fallback's Unreachable, NOT BreakerOpen.
        let out = ProseScorer::score(&scorer, "q", &[chunk("a3", "b")]);
        assert!(
            matches!(out[0], Err(JevError::Unreachable(_))),
            "fallback leg ran with a fresh breaker, got {:?}",
            out[0]
        );
        drop(s1);
        unset_env("JEV_GATEWAY_API_KEY");
        unset_env("JEV_GATEWAY_URL");
    }

    #[test]
    fn fallback_not_fired_when_breaker_opened_by_auth_errors() {
        let _env = env_lock();
        // 401 is NOT fallback-class; the breaker trips on auth and the chain must NOT run.
        set_env("TYPESAFE_API_KEY", "ts");
        set_env("JEV_GATEWAY_API_KEY", "gk");
        set_env("JEV_GATEWAY_URL", "http://127.0.0.1:1/v1/systemone");
        let (p1, s1) = mock_provider("401 Unauthorized", "");
        let mut cfg = provider_config(Provider::Typesafe, None).unwrap();
        cfg.url = format!("http://127.0.0.1:{p1}/v1/systemone");
        cfg.no_cache = true;
        cfg.fallback = Some(Provider::Gateway);
        let scorer = JevScorer::new(cfg);
        scorer.set_sleep(Arc::new(Box::new(|_| {})));
        for i in 0..3 {
            let out = ProseScorer::score(&scorer, "q", &[chunk(&format!("a{i}"), "b")]);
            assert!(matches!(out[0], Err(JevError::AuthRejected { status: 401 })));
        }
        let out = ProseScorer::score(&scorer, "q", &[chunk("a3", "b")]);
        assert!(
            matches!(out[0], Err(JevError::BreakerOpen)),
            "auth-opened breaker must NOT fall back, got {:?}",
            out[0]
        );
        drop(s1);
        unset_env("JEV_GATEWAY_API_KEY");
        unset_env("JEV_GATEWAY_URL");
    }

    #[test]
    fn chain_unchanged_when_fallback_none() {
        let _env = env_lock();
        // No fallback armed: a 402 surfaces as-is (openrouter-only / explicit-choice mode).
        set_env("TYPESAFE_API_KEY", "ts");
        let (p1, s1) = mock_provider("402 Payment Required", "");
        let mut cfg = provider_config(Provider::Typesafe, None).unwrap();
        cfg.url = format!("http://127.0.0.1:{p1}/v1/systemone");
        cfg.no_cache = true;
        cfg.fallback = None;
        let scorer = JevScorer::new(cfg);
        scorer.set_sleep(Arc::new(Box::new(|_| {})));
        let out = ProseScorer::score(&scorer, "q", &[chunk("a", "b")]);
        assert!(matches!(out[0], Err(JevError::InsufficientCredits)));
        drop(s1);
    }

    #[test]
    fn is_fallback_class_covers_availability_only() {
        assert!(is_fallback_class(&JevError::InsufficientCredits));
        assert!(is_fallback_class(&JevError::RateLimited { retry_after: None }));
        assert!(is_fallback_class(&JevError::Timeout));
        assert!(is_fallback_class(&JevError::Unreachable("HTTP 502".into())));
        // Never: malformed answers (a broken query must not double-spend) or auth.
        assert!(!is_fallback_class(&JevError::Malformed("bad shape".into())));
        assert!(!is_fallback_class(&JevError::AuthRejected { status: 401 }));
        assert!(!is_fallback_class(&JevError::NoApiKey { providers_tried: vec![] }));
        assert!(!is_fallback_class(&JevError::BreakerOpen));
        assert!(!is_fallback_class(&JevError::NoGatewayUrl));
    }


    #[test]
    fn privacy_notice_names_backend_and_count() {
        assert_eq!(privacy_notice(7, Provider::Openrouter), "[prose] sending 7 atoms to openrouter");
        assert_eq!(privacy_notice(1, Provider::Gateway), "[prose] sending 1 atoms to gateway");
    }

    // ---- answer parsing: the real OpenRouter decision shape ----

    #[test]
    fn parse_answer_accepts_type_keyed_probability() {
        // The OpenRouter decision API answers `{"noul":0.06,"type":"noul"}` — the
        // probability rides under the verdict-type key. Without this arm every real
        // OpenRouter response parsed as Malformed (found in prose-verb live smoke).
        let v: serde_json::Value = serde_json::from_str(r#"{"noul":0.06,"type":"noul"}"#).unwrap();
        assert_eq!(parse_answer(&v).unwrap(), 0.06);
        // Other shapes still parse.
        let bare: serde_json::Value = serde_json::from_str("0.5").unwrap();
        assert_eq!(parse_answer(&bare).unwrap(), 0.5);
        let obj: serde_json::Value =
            serde_json::from_str(r#"{"probability":0.9}"#).unwrap();
        assert_eq!(parse_answer(&obj).unwrap(), 0.9);
        // A genuinely malformed object still errors.
        let bad: serde_json::Value = serde_json::from_str(r#"{"type":"noul"}"#).unwrap();
        assert!(parse_answer(&bad).is_err());
    }

    // ---- cache key normalization ----

    #[test]
    fn cache_key_normalizes_query_and_hashes_full_text() {
        let a = ProseChunk { id: "x".into(), title: Some("T".into()), keywords: Some("k1 k2".into()), text: "body".into() };
        let b = ProseChunk { id: "y".into(), title: Some("T".into()), keywords: Some("k1 k2".into()), text: "DIFFERENT body".into() };
        let a2 = ProseChunk { id: "OTHER-ID".into(), title: a.title.clone(), keywords: a.keywords.clone(), text: a.text.clone() };
        // Query normalized: trim + collapse internal whitespace + case-fold.
        let k1 = cache_key(Provider::Typesafe, "m", "  Does   IT   Rain? ", &a);
        let k2 = cache_key(Provider::Typesafe, "m", "does it rain?", &a);
        assert_eq!(k1, k2, "query normalized: trim + collapse + casefold");
        // The id NEVER enters the key — same content under a different id is the same atom.
        assert_eq!(
            cache_key(Provider::Typesafe, "m", "q", &a),
            cache_key(Provider::Typesafe, "m", "q", &a2),
            "id-independent key"
        );
        assert_ne!(
            cache_key(Provider::Typesafe, "m", "q", &a),
            cache_key(Provider::Typesafe, "m", "q", &b),
            "different chunk text → different key"
        );
    }
}
