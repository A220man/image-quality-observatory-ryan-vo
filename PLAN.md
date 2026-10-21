# Product development plan

Each round completes one feature or repair. Future items are planned, not implemented claims.

## Current round

automated-quarantine-webhook

## Roadmap

### dataset-ingestion-measurement — Image dataset ingestion, quality measurement and catalog review

Status: done

Acceptance:
- Ingest images in memory and calculate blur, exposure, and contrast metrics without storing raw files.
- Persist quality records in SQLite with duplicate hash detection and batch isolation.
- Provide paginated review table with sorting and filtering by batch and decision.

Implementation: `backend/app/services/metrics.py`, `backend/app/services/catalog.py`, `backend/app/api/routes.py`

Tests: `backend/tests/test_catalog.py`, `backend/tests/test_api.py`

### failure-grouping-clustering — Failure signature grouping and metric clustering

Status: done

Acceptance:
- Group images by identical failure check signatures.
- Cluster standardized metric vectors using deterministic k-means with dominant failure identification.

Implementation: `backend/app/services/grouping.py`, `backend/app/api/routes.py`

Tests: `backend/tests/test_api.py`

### policy-calibration-benchmark — Human label policy calibration and synthetic benchmark suite

Status: done

Acceptance:
- Fit suggested quality policy thresholds from human good/bad feedback labels.
- Evaluate training-set confusion matrix, precision, recall, and F1 score.
- Generate synthetic benchmark scenes and evaluate quality detection accuracy.

Implementation: `backend/app/services/calibration.py`, `backend/app/services/benchmark.py`, `backend/app/services/synthetic.py`

Tests: `backend/tests/test_api.py`

### advisory-llm-explanations — Aggregate-only advisory explanations with multi-provider LLM support

Status: done

Acceptance:
- Generate aggregate-only quality explanations without sending image bytes or identifiers.
- Support OpenAI, Anthropic, Gemini, and Ollama provider endpoints with local offline fallback.

Implementation: `backend/app/services/advisory.py`

Tests: `backend/tests/test_advisory.py`

### decisions-csv-export — Decision CSV export with spreadsheet formula neutralization

Status: done

Acceptance:
- Export batch quality decisions and measurements to CSV format.
- Neutralize spreadsheet formula injection by prefixing special characters.

Implementation: `backend/app/services/export.py`

Tests: `backend/tests/test_export.py`

### oidc-session-auth — OIDC Keycloak authentication with PKCE, session management and demo mode

Status: done

Acceptance:
- Provide OIDC authorization-code flow with PKCE and session cookie management.
- Enforce CSRF token protection on mutating requests and role-based permissions.
- Offer local development demo mode that is refused in production environments.

Implementation: `backend/app/core/auth.py`

Tests: `backend/tests/test_oidc.py`

### quality-distribution-profiling — Dataset quality distribution percentiles and health profiling

Status: done

Acceptance:
- Compute statistical percentiles (p10, p25, p50, p75, p90) and dispersion for all image quality metrics.
- Calculate batch pass/review/reject breakdown and human label agreement rate.
- Expose GET /api/analysis/distribution endpoint and display quality distribution cards in the Analysis tab.

Implementation: `backend/app/services/distribution.py`, `backend/app/api/routes.py`, `frontend/src/App.tsx`, `frontend/src/api.ts`

Tests: `backend/tests/test_distribution.py`, `frontend/src/api.test.ts`

### dataset-drift-comparison — Comparative batch quality drift and Kolmogorov-Smirnov statistical tests

Status: done

Acceptance:
- Compare two dataset batches or time windows to detect distribution drift in blur, exposure, or contrast.
- Compute two-sample Kolmogorov-Smirnov p-values for quality distributions.

Implementation: `backend/app/services/drift.py`, `backend/app/api/routes.py`, `frontend/src/App.tsx`, `frontend/src/api.ts`

Tests: `backend/tests/test_drift.py`

### automated-quarantine-webhook — Automated webhook notifications for high rejection rate batches

Status: done

Acceptance:
- Dispatch signed HMAC webhooks when batch quality rejection rate exceeds configured thresholds.
- Allow operators to configure quarantine thresholds per dataset category.

Implementation: `backend/app/services/webhook.py`, `backend/app/api/routes.py`, `backend/app/main.py`

Tests: `backend/tests/test_webhook.py`

