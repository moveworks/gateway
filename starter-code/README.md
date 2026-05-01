# Moveworks Content Gateway — Starter Code

A ready-to-run Python server for connecting a content source to Moveworks Enterprise Search via the Content Gateway API.

## Requirements

- Python 3.10+
- pip
- A publicly reachable HTTPS URL for your server (required for Moveworks to poll it — see [Deployment](#deployment))

## What's included

| File | Purpose |
|---|---|
| `content_gateway.py` | Demo server and integration starting point — run it immediately, then edit to connect your source |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for the environment variables you'll need to set |
| `openapi.json` | Full Content Gateway API spec |

## What's handled vs. what you implement

The server handles the full Content Gateway protocol — you never write that. What you own is the **source layer**.

| Layer | What it covers | Who writes it |
|---|---|---|
| **Protocol** | OData pagination, Bearer auth, error shapes, rate-limit headers | Done — leave it alone |
| **Source** | Calling your API, field mapping, auth to your system | You |

Two patterns that are inherently system-specific and can't be pre-built for you:

- **Multi-source enumeration** — most systems (SharePoint, Confluence, Google Drive) spread content across sites, spaces, or drives. You enumerate those containers and flatten into one stream inside `fetch_files_from_source`.
- **Permission inheritance** — many systems store ACLs on folders or spaces, not individual documents. You walk the container hierarchy to resolve effective access inside `fetch_permissions_for_file`.

Each source function has a docstring that explains which of these applies and what to do about it.

## Step 1 — Verify connectivity with the demo server

Install dependencies and generate an API key:

```bash
pip install -r requirements.txt
python -c "import secrets; print(secrets.token_hex(32))"
```

Start the demo server with your key:

```bash
GATEWAY_API_KEY=<your-key> python content_gateway.py
```

The server starts on port 5001 and returns built-in sample data (Acme IT Knowledge Portal). Expose it over HTTPS (see [Deployment](#deployment)), configure the connector in Moveworks Setup, and trigger an initial sync to confirm Moveworks can reach it.

## Step 2 — Connect your source system

Edit `content_gateway.py` directly. The file has three labeled sections:

**Section 1 — Configuration**

Set `SOURCE_API_BASE_URL` to your API's base URL. Then uncomment the `_source_headers()` block that matches your auth method — Bearer token, API key header, OAuth2 client credentials, or no auth. One change there applies everywhere.

**Section 2 — Source functions**

Implement the `fetch_*` functions. These call your source API and return raw data. Read the docstring on each function before implementing it — they explain what to return, what pagination patterns to handle, and whether your system is likely to require multi-source enumeration or permission inheritance.

**Section 3 — Mapper functions**

Update the field names in `map_item_to_node` (and `map_item_to_user`, `map_item_to_group` if you sync identity) to match your API's response shape. Search for `# TODO` comments.

**Set credentials and run:**

```bash
cp .env.example .env
# fill in your values
export $(cat .env | xargs)
python content_gateway.py
```

## Step 3 — Connect to Moveworks

Once your server is deployed and reachable over HTTPS:

1. In **Moveworks Setup**, go to **Enterprise Search > Content Gateway**
2. Click **Add Gateway** and enter your gateway's public base URL
3. Set authentication to **API Key** and paste your `GATEWAY_API_KEY` value
4. Save and trigger an initial sync
5. Go to **Enterprise Search > Resource Permissions**, select your connector, and set the permission model to **ReBAC**
6. Go to **User Identity**, add your Content Gateway as an identity source, and trigger a sync

## Deployment

Moveworks polls your gateway on a schedule, so it must be reachable over HTTPS. Common options:

| Platform | How to deploy |
|---|---|
| **AWS Lambda** | Wrap with a WSGI adapter (e.g. `mangum`) and deploy with `handler` as the entry point |
| **Azure App Service** | Push to App Service and set environment variables in Application Settings |
| **Heroku** | `heroku create && git push heroku main`, then `heroku config:set GATEWAY_API_KEY=...` |
| **Any container / VM** | Standard Flask app — run behind nginx or any reverse proxy |

For local testing, [ngrok](https://ngrok.com) or [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) can expose your local server over HTTPS temporarily.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GATEWAY_API_KEY` | Yes | The key Moveworks sends to authenticate to your gateway — you generate this value |
| `SOURCE_API_BASE_URL` | Yes | Your source system's API base URL |
| `SOURCE_API_KEY` | Depends | Your source system credential — rename to match your system |
| `PORT` | No | Override the default port (default: `5001`) |

Copy `.env.example` to `.env` for local development. Never commit `.env` to source control.
