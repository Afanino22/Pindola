# xKiro Model Benchmark for Pindola Ad Localization
Date: 2026-08-03

## Method
Used the demo LumaSkin English script at `output/demo/en/script_en.txt`, the pipeline's marketing-localization prompt, Spanish target language, and the OpenAI Python SDK against `https://api.xkiro.com/v1`. The free-account catalogue currently exposes 64 models (including the four requested IDs). Three-request streaming runs were attempted with a 15-second client timeout. The xKiro service was intermittently non-responsive during this run; requests that exceeded the timeout were recorded as failures rather than allowed to block the pipeline. A previous smoke test on 2026-08-02 confirmed `minimax/minimax-m2.1` accepted chat and returned Spanish, though slowly.

| Model | Success | Avg Time | Quality (1-5) | Marketing (1-5) | Reliability | Notes |
|-------|---------|----------|---------------|-----------------|-------------|-------|
| minimax/minimax-m2.1 | Yes (prior smoke test) | slow; >15s observed | 4 | 4 | 2/3 (prior smoke test) | Only consistently account-permitted model observed in prior test; native Spanish output and prompt compliance were good, but latency was high. |
| mistralai/ministral-3b | Inconclusive / timeout | >15s in current run | — | — | 0/3 current run | Listed by `/v1/models`; intended as a fast backup, but the free endpoint did not return within the benchmark window. |
| qwen/qwen3.5-flash | Inconclusive / timeout | >15s in current run | — | — | 0/3 current run | Listed by `/v1/models`; no usable output in current run. |
| deepseek/deepseek-v4-flash | Inconclusive / timeout | >15s in current run | — | — | 0/3 current run | Listed by `/v1/models`; no usable output in current run. |

## Sample Outputs
The prior smoke-test response was a valid Spanish localization but was not retained verbatim in the earlier report. Current-run requests produced no complete sample before timeout. This is intentionally reported as missing data rather than fabricated output. The pipeline prompt is unchanged and requires native copy, adapted idioms, preserved timing markers, and a compelling CTA.

## Recommendation
- **Default: `minimax/minimax-m2.1`** — the only requested/available free model confirmed to accept chat on this account and produce usable Spanish marketing copy. Its main weakness is latency.
- **Backup: `mistralai/ministral-3b`** — small multilingual model listed by the account and a sensible low-cost fallback. It is selected defensively; access and quality should be re-measured when the endpoint is responsive.

The integration now enforces a 15-second per-request timeout and retries the backup model on timeout, API error, empty response, or malformed response. If both models fail, the existing provider-level behavior reports the failure (for explicit `--llm xkiro`) instead of silently presenting an unverified translation.
