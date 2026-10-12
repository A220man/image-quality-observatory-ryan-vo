# Changelog

## 1.1.0 — work-in-progress checkpoint

Partial code published for continued development. Known issues: STATUS.md.

## Unreleased

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
