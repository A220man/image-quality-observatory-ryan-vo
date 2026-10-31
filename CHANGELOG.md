# Changelog

## 1.5.0 — work-in-progress checkpoint

Partial code published for continued development. Known issues: STATUS.md.

## 1.4.0 — work-in-progress checkpoint

Partial code published for continued development. Known issues: STATUS.md.

## 1.3.1 — work-in-progress checkpoint

Partial code published for continued development. Fixed webhook async dispatch reliability.

## 1.3.0 — work-in-progress checkpoint
## 1.2.0 — work-in-progress checkpoint

Partial code published for continued development. Known issues: STATUS.md.

## 1.1.0 — work-in-progress checkpoint

Partial code published for continued development. Known issues: STATUS.md.

## [1.3.0] - 2026-10-21

- Automated quarantine webhook notifications with HMAC-SHA256 signing for high rejection rate batches.
- Configurable rejection rate thresholds per dataset category via admin API (`POST/PATCH/GET/DELETE /api/webhooks`).
- Batch quarantine check endpoint (`POST /api/webhooks/check/{batch}`) to evaluate and dispatch webhooks.
- Webhook test endpoint (`POST /api/webhooks/{id}/test`) for operator validation.
- Delivery logging with status codes, response bodies, and error tracking.

## Unreleased

- Comparative batch quality drift detection using two-sample Kolmogorov-Smirnov tests across all quality metrics (blur, luminance, edge density, clipping, contrast, dynamic range, quality score).
- Authenticated `GET /api/analysis/drift` endpoint with batch selection and configurable significance level.
- Drift comparison tab in the frontend workspace showing per-metric KS statistics, p-values, and drift flags.
- Statistical distribution profiling and percentile analysis (p10, p25, p50, p75, p90) for all image quality metrics.
- Dataset quality health status rating and decision breakdown (accept, review, reject rates).
- Human feedback label alignment rate and concordance measurement.
- Authenticated `GET /api/analysis/distribution` endpoint with batch filtering.
- Quality distribution summary table, health badges, and failure check frequencies in the frontend workspace.
## [1.0.0] - 2026-10-09

- Image quality metrics, batch ingestion and replay-safe duplicate handling.
- Human labels, policy re-evaluation, failure signatures and deterministic metric clustering.
- Threshold calibration and held-out synthetic benchmark.
- OIDC sign-in, server-side sessions, CSRF checks, roles and audit events.
- Aggregate-only optional LLM advice with local fallback.
- React review workspace, container deployment and regression tests.

## 1.1.0 — work-in-progress checkpoint

Partial code published for continued development. Known issues: STATUS.md.

## Unreleased

- Comparative batch quality drift detection using two-sample Kolmogorov-Smirnov tests across all quality metrics (blur, luminance, edge density, clipping, contrast, dynamic range, quality score).
- Authenticated `GET /api/analysis/drift` endpoint with batch selection and configurable significance level.
- Drift comparison tab in the frontend workspace showing per-metric KS statistics, p-values, and drift flags.
- Statistical distribution profiling and percentile analysis (p10, p25, p50, p75, p90) for all image quality metrics.
- Dataset quality health status rating and decision breakdown (accept, review, reject rates).
- Human feedback label alignment rate and concordance measurement.
- Authenticated `GET /api/analysis/distribution` endpoint with batch filtering.
- Quality distribution summary table, health badges, and failure check frequencies in the frontend workspace.
## [1.0.0] - 2026-10-09

- Image quality metrics, batch ingestion and replay-safe duplicate handling.
- Human labels, policy re-evaluation, failure signatures and deterministic metric clustering.
- Threshold calibration and held-out synthetic benchmark.
- OIDC sign-in, server-side sessions, CSRF checks, roles and audit events.
- Aggregate-only optional LLM advice with local fallback.
- React review workspace, container deployment and regression tests.
