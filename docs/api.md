# HTTP API

Responses are JSON except CSV export and empty successful delete/logout responses. Errors use `{"error":{"code":"...","message":"..."}}`; validation errors also contain field details. All application data endpoints require a session. Mutations require `X-CSRF-Token` from `/api/auth/me`.

| Method | Route | Role | Behavior |
|---|---|---|---|
| GET | `/api/health` | Public | Readiness and version |
| GET | `/api/auth/mode` | Public | Login mode |
| GET | `/api/auth/login` | Public | Start OIDC authorization with PKCE |
| GET | `/api/auth/callback` | Browser-bound state | Exchange code and establish session |
| POST | `/api/auth/demo` | Local development only | Create local administrator session |
| GET | `/api/auth/me` | Signed in | Username, roles and CSRF token |
| POST | `/api/auth/logout` | Signed in | Revoke session; 204 |
| POST | `/api/images` | Reviewer | Multipart `file`, optional `batch`; metrics and duplicate status |
| GET | `/api/images` | Viewer | `batch`, `decision`, `limit` (1–500), `offset`; items and total |
| GET | `/api/images/{id}` | Viewer | Stored measurements and label |
| PATCH | `/api/images/{id}/label` | Reviewer | JSON `label`: `good`, `bad` or null |
| DELETE | `/api/images/{id}` | Admin | Delete image metadata, retain audit; 204 |
| GET | `/api/policy` | Viewer | Current thresholds |
| PUT | `/api/policy` | Admin | Save policy and atomically re-evaluate all images |
| GET | `/api/analysis/groups` | Viewer | Exact failure signatures; optional `batch` |
| GET | `/api/analysis/clusters` | Viewer | Metric clusters; optional `batch`, `k` (1–12) |
| POST | `/api/analysis/calibrate` | Reviewer | Suggest policy from ≥4 labeled images with both classes |
| POST | `/api/analysis/benchmark` | Reviewer | Synthetic benchmark; `scenes` (4–24), `seed` |
| POST | `/api/analysis/advice` | Reviewer | Optional aggregate-only advice; optional `batch` |
| GET | `/api/exports/decisions.csv` | Viewer | CSV download; optional `batch` |
| GET | `/api/audit` | Admin | Latest events; `limit` (1–500) |

Admins inherit reviewer and viewer access; reviewers inherit viewer access. Unknown identity roles become viewer only. Image uploads default to 12 MiB and a 40-million-pixel decode bound. Invalid or unsupported images return 422; oversized bodies return 413. Identical bytes in the same batch return the existing image with `created: false`.

Policy body:

```json
{"blur_min":100,"luma_min":50,"luma_max":205,"clip_max":0.08,"contrast_min":0.1,"review_margin":0.15}
```

Label request:

```json
{"label":"good"}
```

CSV string cells beginning with spreadsheet formula markers are prefixed with an apostrophe. IDs, hashes, decisions, labels and metrics allow joining exported decisions to the original dataset; image bytes are never exported.
