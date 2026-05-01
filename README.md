# Moveworks Content Gateway

Build custom content integrations for Moveworks Enterprise Search using the Content Gateway API.

Read the full documentation at [developer.moveworks.com](https://developer.moveworks.com/api-reference/content-gateway/starter-code).

---

## What's in this repo

### `starter-code/` — Reference Implementation

A ready-to-run Flask server that implements the full Content Gateway protocol. Run it immediately to verify connectivity with Moveworks, then edit it to connect your source system.

| File | Purpose |
|---|---|
| `content_gateway.py` | Demo server and integration starting point |
| `requirements.txt` | Python dependencies (`flask`, `requests`) |
| `.env.example` | Template for the environment variables you'll need to set |
| `openapi.json` | Full Content Gateway API spec |

**Quick start:**

```bash
cd starter-code
pip install -r requirements.txt
GATEWAY_API_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") python content_gateway.py
```

See `starter-code/` for the full integration guide.

### `starter-code/load-testing/` — Load Testing Server

A separate server that generates synthetic documents at configurable scale (up to 50,000 files across multiple file size distributions). Use it to stress-test Moveworks content ingestion before connecting a real source.

```bash
cd starter-code/load-testing
pip install flask
python load_test_gateway.py
```

### `starter-code/legacy gateways/` — Legacy Implementations

Sample gateway implementations for legacy Moveworks connector types. For new integrations, use `content_gateway.py` instead.

---

For additional support, contact [Moveworks Professional Services](https://developer.moveworks.com/creator-studio/troubleshooting/support).
