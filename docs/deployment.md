# Deployment and organization login

## OIDC

Register a confidential or public authorization-code client with PKCE S256 at your identity provider. Configure the exact redirect URI `https://YOUR_APPLICATION_HOST/api/auth/callback`; do not use wildcard redirects. Set its discovery URL, client ID and, for confidential clients, client secret in `.env`. The discovery issuer must match the URL prefix before `/.well-known/openid-configuration`.

The application verifies RS256 or ES256 signatures from the issuer's JWKS, issuer, audience, expiration, issued-at time, authorized party when supplied, and nonce. Browser-bound state and PKCE bind the callback to the initiating browser. Each state is consumed once and expires after ten minutes. Session cookies are HttpOnly, Secure in production, and SameSite=Lax. The database stores hashes of opaque session identifiers.

Map organization groups into a claim containing a list of `viewer`, `reviewer`, or `admin`. Default claim path is `realm_access.roles`; override `OIDC_ROLE_CLAIM` for your provider. Assign least-privilege roles through the IdP. Role changes take effect on the next session; revoke existing sessions when immediately removing access. No public signup or built-in password store is provided.

## SAML organizations

SAML is supported through an identity broker, not a custom SAML parser inside this application. Configure your existing broker (for example Keycloak) with the organization's SAML identity provider, exchange metadata and signing certificates with the IdP, enforce signed assertions/responses, and configure the broker's OIDC client as above. Map SAML groups to the application roles in the broker. The browser then follows application → OIDC broker → SAML IdP → broker → application. Your IdP administrator must supply actual metadata and role mappings; this repository does not ship a universal IdP or demo production credential.

Validate sign-in and logout using your organization's test accounts before deployment. Automated tests cover the OIDC protocol with a local signing key and mocked endpoints; they do not certify a particular SAML tenant configuration.

## HTTPS and containers

`compose.yaml` binds the frontend to `127.0.0.1:8080`. Terminate HTTPS in your host reverse proxy and forward to that port. `FRONTEND_URL` must be the origin only, for example `https://images.example.com`. Set `OIDC_REDIRECT_URI` to that origin plus `/api/auth/callback`. Keep `.env` readable only by the operator and outside version control.

Do not set demo mode or disable secure cookies to make production sign-in work. Use local installation instructions for a demo. The default Nginx upload limit is 13 MiB including multipart overhead; if changing `MAX_UPLOAD_BYTES`, adjust that limit too. Backend settings `MAX_IMAGE_PIXELS`, `SESSION_TTL_SECONDS` and `LLM_TIMEOUT_SECONDS` must be positive finite values.

The Docker service is one API process with a writable `/data` volume and temporary `/tmp`. Do not horizontally replicate SQLite across independent volumes. Set resource limits appropriate to image decoding and benchmark concurrency at your container orchestrator or reverse proxy.

## Backups and updates

Stop the API before a filesystem-level volume backup, or use SQLite's online backup API to produce a consistent snapshot. Preserve audit records according to your organization's requirements. Restore to a separate environment and verify `/api/health`, sign-in and a test dataset before replacing production. Upgrade by backing up the volume, building the release images, and restarting the service. Rollback also requires restoring the matching backup if a future release introduces an incompatible schema migration.

## Credentials and provider privacy

Only the server receives `LLM_API_KEY` and `OIDC_CLIENT_SECRET`. The frontend build receives neither. Provider calls contain counts, decisions, failure frequencies and mean quality only. The app does not fetch user-supplied URLs or run provider instructions. Protect provider endpoints in deployment configuration; ordinary reviewers cannot change them through the UI.
