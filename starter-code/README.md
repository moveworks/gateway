# Moveworks Content Gateway: Starter Code

A ready-to-run Python server for connecting a content source to Moveworks Enterprise Search via the Content Gateway API.

## Requirements

- Python 3.10+
- pip
- A publicly reachable HTTPS URL for your server (required for Moveworks to poll it. See [Deployment](#deployment))

## What's included

| File | Purpose |
|---|---|
| `content_gateway.py` | Demo server and integration starting point. Run it immediately, then edit to connect your source |
| `validate.py` | Schema validator. Run against any live server to confirm your responses conform to the Content Gateway API |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for the environment variables you'll need to set |
| `openapi.json` | Full Content Gateway API spec |

## What's handled vs. what you implement

The server handles the full Content Gateway protocol. You never write that. What you own is the **source layer**.

| Layer | What it covers | Who writes it |
|---|---|---|
| **Protocol** | OData pagination, Bearer auth, error shapes | Done: leave it alone |
| **Rate-limit headers** | The hook is in place, but values are commented out by default | Uncomment and wire up to your real rate-limit budget when you go to production |
| **Source** | Calling your API, field mapping, auth to your system | You |

Two patterns that are inherently system-specific and can't be pre-built for you:

- **Multi-source enumeration**: most systems (SharePoint, Confluence, Google Drive) spread content across sites, spaces, or drives. You enumerate those containers and flatten into one stream inside `fetch_files_from_source`.
- **Permission inheritance**: many systems store ACLs on folders or spaces, not individual documents. You walk the container hierarchy to resolve effective access inside `fetch_permissions_for_file`.

Each source function has a docstring that explains which of these applies and what to do about it.

## Step 1: Verify connectivity with the demo server

Install dependencies and generate an API key:

```bash
pip install -r requirements.txt
python -c "import secrets; print(secrets.token_hex(32))"
```

Start the demo server with your key:

```bash
GATEWAY_API_KEY=<your-key> python content_gateway.py
```

The server starts on port 5001 and returns built-in sample data (Acme IT Knowledge Portal). Validate that all endpoints are responding correctly before connecting Moveworks:

```bash
GATEWAY_API_KEY=<your-key> python validate.py --rebac
```

Once all checks pass, expose the server over HTTPS (see [Deployment](#deployment)) and follow the [Connecting Your Gateway to Moveworks](https://docs.moveworks.com/api-reference/content-gateway/moveworks-setup) guide to configure the connector.

## Step 2: Connect your source system

Edit `content_gateway.py` directly. The file has three labeled sections:

**Section 1: Configuration**

Set `SOURCE_API_BASE_URL` to your API's base URL. Then uncomment the `_source_headers()` block that matches your auth method (Bearer token, API key header, OAuth2 client credentials, or no auth). One change there applies everywhere.

**Section 2: Source functions**

Implement the `fetch_*` functions. These call your source API and return raw data. Read the docstring on each function before implementing it. They explain what to return, what pagination patterns to handle, and whether your system is likely to require multi-source enumeration or permission inheritance.

**Section 3: Mapper functions**

Update the field names in `map_item_to_node` (and `map_item_to_user`, `map_item_to_group` if you sync identity) to match your API's response shape. Search for `# TODO` comments.

**Set credentials and run:**

```bash
cp .env.example .env
# fill in your values
export $(cat .env | xargs)
python content_gateway.py
```

## Testing the demo end-to-end with a real Moveworks tenant

The demo's sample users have hardcoded emails (`sarah.chen@acmecorp.internal`, etc.) that won't match any real Moveworks user identity. If you connect this server to your Moveworks tenant as-is, content will ingest successfully but won't surface in search for any real user because Moveworks can't resolve any of the demo identities.

To test end-to-end, set `DEMO_TEST_USER_EMAILS` to your real work email before starting the server:

```bash
DEMO_TEST_USER_EMAILS=you@yourcompany.com \
GATEWAY_API_KEY=<your-key> \
python content_gateway.py
```

You'll be injected as a sample user, added to `group-it-staff`, and through nested group membership in `group-all-employees` you'll have access to `kb-001` through `kb-007`. You will NOT have access to `kb-008` (HR), `kb-009`, or `kb-010` (Executives), so you can verify permission enforcement is working: those documents should be hidden from your search results in the AI Assistant even though they're ingested.

For multiple test users (e.g., for a small QA group), comma-separate the emails.

### End-to-end test sequence

1. Set `DEMO_TEST_USER_EMAILS` and start the server (above).
2. Expose it over HTTPS (see [Deployment](#deployment) — `ngrok` works for testing).
3. In **Moveworks Setup**, create the Content Gateway connector pointing at your HTTPS URL.
4. Trigger an initial sync. Wait for completion under **Enterprise Search > Indexed Content > Files** (typically under 30 minutes for the 10-file demo set).
5. Open Moveworks AI Assistant as your real user.
6. Search for content from the demo (try "VPN setup" for `kb-001`, "incident response" for `kb-004`).
7. Verify HR-restricted content is hidden — search for "compensation" or "salary"; `kb-008` should not appear.

## Validating the schema

Before connecting to Moveworks, validate that your real source is returning the correct schema:

```bash
# Files only - if using Public to all permission strategy
python validate.py

# Full validation - if using ReBAC permission strategy
python validate.py --rebac
```

See the [Verifying Your Build](https://docs.moveworks.com/api-reference/content-gateway/verifying-your-build) guide for a full explanation of what the validator checks and how to fix common failures.

## Capacity planning

Moveworks performs scheduled **full sync runs** against your gateway. Each run walks the complete inventory of files, file metadata, file permissions, groups, group memberships, and users. There isn't an incremental-diff mode that only fetches changes.

The main cost savings between syncs come from the **file binary cache**. If you return an accurate `last_modified_datetime` on every file, Moveworks skips re-downloading binaries whose timestamp hasn't changed since the previous sync. File metadata, permissions, group memberships, and users are re-walked each run, but binary downloads (typically the largest payloads) are skipped for unchanged files.

**Concurrent scheduled syncs are skipped, not stacked.** If your previous sync is still running when the next scheduled run would fire, the next run is skipped until the current one completes. You won't see overlapping load on your backend even if first sync exceeds your scheduled cadence.

If your backend has limited capacity, use rate-limit signals to bound the call rate:

- **Proactive**: return `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers on every response. Moveworks paces its calls to fit your advertised capacity, slowing down before you have to fail anything. Variant header names (`X-Rate-Limit-*`, `RateLimit-*`) are also recognized.
- **Reactive**: return `429 Too Many Requests` with a `Retry-After` header. Moveworks honors the wait value and retries.

Returning fewer items per response than the requested `$top` (with `@odata.nextLink` for the rest) is also a clean way to bound per-request work. Useful when your backend can't sustain large response payloads.

## Step 3: Connect to Moveworks

Once your server is deployed and reachable over HTTPS:

1. In **Moveworks Setup**, navigate to **Core Platform > Connectors > Built-in Connectors** and select **Content Gateway System**
2. Enter your gateway's public base URL, set authentication to **API Key**, and paste your `GATEWAY_API_KEY` value
3. Navigate to **Enterprise Search > Configure Search > Classic Ingestion > Files** and click **Create** to configure the ingestion
4. Save and trigger an initial sync
5. Navigate to **Enterprise Search > Resource Permissions > Permission Rules**, click **Create**, and configure your permission strategy (ReBAC or Public)
6. If using ReBAC, go to **User Identity**, add your Content Gateway as an identity source, and trigger a sync

## Deployment

Moveworks polls your gateway on a schedule, so it must be reachable over HTTPS. Common options:

| Platform | How to deploy |
|---|---|
| **AWS Lambda** | Wrap with a WSGI adapter (e.g. `mangum`) and deploy with `handler` as the entry point |
| **Azure App Service** | Push to App Service and set environment variables in Application Settings |
| **Heroku** | `heroku create && git push heroku main`, then `heroku config:set GATEWAY_API_KEY=...` |
| **Any container / VM** | Standard Flask app. Run behind nginx or any reverse proxy |

For local testing, [ngrok](https://ngrok.com) or [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) can expose your local server over HTTPS temporarily.

### Concurrency note for production

The bare `python content_gateway.py` command runs Flask in single-threaded mode. Fine for local testing, **not fine for production**. Moveworks issues multiple concurrent requests against your gateway during a sync (typically up to 20 at once against the same domain). With single-threaded Flask, those requests serialize: each one waits for the previous to finish.

The consequences for a large deployment:

- **First sync stretches dramatically.** A workload that should take an hour with parallelism takes most of a day in series.
- **Individual requests are more likely to hit timeouts.** A request queued behind 19 others may exceed Moveworks' per-response deadline before it's even handled.
- **Your backend never benefits from parallelism it could otherwise use.** If your underlying data store is fine with concurrent reads, single-threaded Flask is leaving capacity on the table.

Whichever production host you use, configure it for **concurrent request handling**. The exact mechanism depends on your platform (WSGI worker processes, container concurrency settings, function-as-a-service concurrency limits), but the principle is the same: your gateway should be able to handle multiple in-flight requests simultaneously.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GATEWAY_API_KEY` | Yes | The key Moveworks sends to authenticate to your gateway. You generate this value |
| `SOURCE_API_BASE_URL` | Yes | Your source system's API base URL |
| `SOURCE_API_KEY` | Depends | Your source system credential. Rename to match your system |
| `PORT` | No | Override the default port (default: `5001`) |

Copy `.env.example` to `.env` for local development. Never commit `.env` to source control.
