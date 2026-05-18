"""
Moveworks Content Gateway: Schema Validator
════════════════════════════════════════════
Validates that a running Content Gateway server returns responses that
conform to the Moveworks Content Gateway API schema.

Run this against your server at any stage:
  - Against the demo server before connecting a real source
  - Against your real source after editing content_gateway.py
  - Against any deployed instance before connecting Moveworks

Works for any source system. It tests protocol conformance, not content.

USAGE
─────
  # Set env vars
  export GATEWAY_API_KEY=your-key
  export SERVER_URL=http://localhost:5001   # default if not set

  # Validate files only (use when Strategy Config is Public to all)
  python validate.py

  # Full validation including users, groups, and permissions (use for ReBAC)
  python validate.py --rebac

  # Validate against a deployed server
  SERVER_URL=https://your-gateway.example.com python validate.py --rebac
"""

import argparse
import os
import sys

import requests

# ── Configuration ──────────────────────────────────────────────────────────────

SERVER_URL  = os.environ.get("SERVER_URL", "http://localhost:5001").rstrip("/")
API_KEY     = os.environ.get("GATEWAY_API_KEY", "")

PASS  = "\033[32m✓\033[0m"
FAIL  = "\033[31m✗\033[0m"
WARN  = "\033[33m⚠\033[0m"
SKIP  = "\033[90m–\033[0m"

# ── Helpers ────────────────────────────────────────────────────────────────────

errors_found = 0


def check(label: str, passed: bool, detail: str = "") -> bool:
    global errors_found
    symbol = PASS if passed else FAIL
    suffix = f"  {detail}" if detail else ""
    print(f"  {symbol} {label}{suffix}")
    if not passed:
        errors_found += 1
    return passed


def warn(label: str, detail: str = ""):
    suffix = f"  {detail}" if detail else ""
    print(f"  {WARN} {label}{suffix}")


def section(title: str):
    print(f"\n{title}")
    print("─" * len(title))


def get(path: str, key: str = API_KEY) -> tuple[int, dict]:
    try:
        r = requests.get(f"{SERVER_URL}{path}", headers={"Authorization": f"Bearer {key}"}, timeout=10)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}
    except requests.exceptions.ConnectionError:
        print(f"\n  {FAIL} Could not connect to {SERVER_URL}")
        print(f"     Is the server running? Start it with:")
        print(f"     GATEWAY_API_KEY=<key> python content_gateway.py\n")
        sys.exit(1)


def has_keys(obj: dict, *keys) -> tuple[bool, str]:
    missing = [k for k in keys if k not in obj]
    return (True, "") if not missing else (False, f"missing fields: {', '.join(missing)}")


# ── Validators ─────────────────────────────────────────────────────────────────

def validate_auth():
    section("Authentication")

    status, _ = get("/v1/files", key="wrong-key")
    check("Rejects invalid API key with 401", status == 401, f"got HTTP {status}")

    r = requests.get(f"{SERVER_URL}/v1/files", timeout=10)
    check("Rejects missing Authorization header with 401", r.status_code == 401, f"got HTTP {r.status_code}")

    r = requests.get(f"{SERVER_URL}/v1/files", headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10)
    check("Accepts valid API key", r.status_code == 200, f"got HTTP {r.status_code}")

    # Rate-limit headers are advisory but recommended. Moveworks reads them to
    # pace its call rate. Warn if missing rather than fail.
    rl_headers = {h.lower() for h in r.headers}
    has_rl = any(h.startswith(("x-ratelimit-", "x-rate-limit-", "ratelimit-")) for h in rl_headers)
    if has_rl:
        check("Emits rate-limit headers (X-RateLimit-* or RFC 9456 variants)", True)
    else:
        warn("No rate-limit headers found on response",
             "Moveworks reads X-RateLimit-Limit/Remaining/Reset to throttle proactively. Recommended for production.")


def validate_permissions_metadata():
    section("GET /v1/files/permissions/metadata")

    status, body = get("/v1/files/permissions/metadata")

    if status == 404:
        warn("Endpoint returned 404. Not implemented",
             "Required for ReBAC. Should return {\"model\": \"resource_permission\"}.")
        return

    if not check("Returns HTTP 200", status == 200, f"got {status}"):
        return

    model = body.get("model")
    check(
        "Reports model='resource_permission' (the only supported model)",
        model == "resource_permission",
        f"got model='{model}'",
    )


def validate_files() -> list[dict]:
    section("GET /v1/files")

    status, body = get("/v1/files")
    if not check("Returns HTTP 200", status == 200, f"got {status}"):
        return []

    ok, detail = has_keys(body, "value", "@odata.context")
    check("Response has required envelope fields (value, @odata.context)", ok, detail)

    files = body.get("value", [])
    check("Returns at least one file", len(files) > 0, f"got {len(files)} files")

    if not files:
        return []

    print(f"       {len(files)} file(s) returned")

    issues = []
    for i, f in enumerate(files):
        label = f.get("name", f"file[{i}]")

        ok, detail = has_keys(f, "id", "name", "external_url", "last_modified_datetime", "content")
        if not ok:
            issues.append(f"{label}: {detail}")
            continue

        content = f.get("content", {})
        if "mime_type" not in content:
            issues.append(f"{label}: content missing mime_type")
        elif content["mime_type"] != "text/html":
            if "download_path" not in content:
                issues.append(f"{label}: binary content missing download_path field")
        # HTML body is not required in the /files list response. Moveworks
        # re-fetches it via /files/{id}. The body check happens there instead.

        if f.get("status") not in ("active", "deleted", None):
            issues.append(f"{label}: status must be 'active' or 'deleted', got '{f.get('status')}'")

    check(
        "All files have required fields and valid content shape",
        len(issues) == 0,
        f"\n" + "\n".join(f"       · {i}" for i in issues) if issues else ""
    )

    return files


def validate_single_file(files: list[dict]):
    if not files:
        return
    # Prefer testing an HTML file if available, so we can verify the inline-body
    # contract that Moveworks reads from this endpoint.
    html_files = [f for f in files if f.get("content", {}).get("mime_type") == "text/html"]
    test_file = html_files[0] if html_files else files[0]
    file_id = test_file["id"]
    section(f"GET /v1/files/{{id}}  (testing id={file_id})")

    status, body = get(f"/v1/files/{file_id}")
    if not check("Returns HTTP 200", status == 200, f"got {status}"):
        return

    file = body.get("value", {})
    ok, detail = has_keys(file, "id", "name", "external_url", "last_modified_datetime", "content")
    check("File object has required fields", ok, detail)
    check("Returned file id matches requested id", file.get("id") == file_id,
          f"requested {file_id}, got {file.get('id')}")

    # HTML body must be inline on /files/{id}. This is where Moveworks reads it.
    content = file.get("content", {})
    if content.get("mime_type") == "text/html":
        check(
            "text/html content includes inline body on /files/{id}",
            bool(content.get("body")),
            "Moveworks reads HTML content from this endpoint's body field, not from /files",
        )


def validate_permissions(files: list[dict]):
    if not files:
        return
    file_id = files[0]["id"]
    section(f"GET /v1/files/{{id}}/permissions  (testing id={file_id})")

    status, body = get(f"/v1/files/{file_id}/permissions")

    if status == 404:
        warn("Endpoint returned 404. Not implemented",
             "Required for ReBAC. Implement fetch_permissions_for_file() in Section 2.")
        return

    if not check("Returns HTTP 200", status == 200, f"got {status}"):
        return

    value = body.get("value", {})
    ok, detail = has_keys(value, "permissions")
    if not check("Response has permissions array", ok, detail):
        return

    permissions = value.get("permissions", [])
    check("At least one permission entry returned", len(permissions) > 0, f"got {len(permissions)}")

    issues = []
    wildcard_issues = []
    for i, p in enumerate(permissions):
        ok, detail = has_keys(p, "id", "type", "action")
        if not ok:
            issues.append(f"permission[{i}]: {detail}")
            continue
        if p.get("type") not in ("USER", "GROUP"):
            issues.append(f"permission[{i}]: type must be USER or GROUP, got '{p.get('type')}'")
        if p.get("action") != "VIEW":
            issues.append(f"permission[{i}]: action must be VIEW, got '{p.get('action')}'")
        # Wildcard antipattern: id "*" only works as a public-access wildcard
        # when paired with type "GROUP". USER+* will not behave as a wildcard.
        if p.get("id") == "*" and p.get("type") != "GROUP":
            wildcard_issues.append(
                f"permission[{i}]: {{type: '{p.get('type')}', id: '*'}} is not a working "
                "wildcard. Only {type: 'GROUP', id: '*'} grants access to all users"
            )

    check(
        "All permission entries have valid shape",
        len(issues) == 0,
        f"\n" + "\n".join(f"       · {i}" for i in issues) if issues else ""
    )

    if wildcard_issues:
        for w in wildcard_issues:
            warn(w)


def validate_users():
    section("GET /v1/users")

    status, body = get("/v1/users")

    if status == 404:
        warn("Endpoint returned 404. Not implemented",
             "Required for ReBAC. Implement fetch_users_from_source() in Section 2.")
        return

    if not check("Returns HTTP 200", status == 200, f"got {status}"):
        return

    users = body.get("value", [])
    check("Returns at least one user", len(users) > 0, f"got {len(users)}")
    print(f"       {len(users)} user(s) returned")

    issues = []
    for i, u in enumerate(users):
        ok, detail = has_keys(u, "id", "primary_email_addr")
        if not ok:
            issues.append(f"user[{i}]: {detail}")

    check(
        "All users have required fields (id, primary_email_addr)",
        len(issues) == 0,
        f"\n" + "\n".join(f"       · {i}" for i in issues) if issues else ""
    )


def validate_groups():
    section("GET /v1/groups")

    status, body = get("/v1/groups")

    if status == 404:
        warn("Endpoint returned 404. Not implemented",
             "Required for ReBAC. Implement fetch_groups_from_source() in Section 2.")
        return

    if not check("Returns HTTP 200", status == 200, f"got {status}"):
        return

    groups = body.get("value", [])
    check("Returns at least one group", len(groups) > 0, f"got {len(groups)}")
    print(f"       {len(groups)} group(s) returned")

    issues = []
    for i, g in enumerate(groups):
        ok, detail = has_keys(g, "id")
        if not ok:
            issues.append(f"group[{i}]: {detail}")

    check(
        "All groups have required id field",
        len(issues) == 0,
        f"\n" + "\n".join(f"       · {i}" for i in issues) if issues else ""
    )

    # Spot-check members for the first group
    if groups:
        group_id = groups[0]["id"]
        section(f"GET /v1/groups/{{id}}/members  (testing id={group_id})")
        status, body = get(f"/v1/groups/{group_id}/members")

        if status == 404:
            warn("Members endpoint returned 404. Not implemented",
                 "Required for ReBAC group resolution.")
            return

        if not check("Returns HTTP 200", status == 200, f"got {status}"):
            return

        members = body.get("value", [])
        print(f"       {len(members)} member(s) returned")

        issues = []
        for i, m in enumerate(members):
            ok, detail = has_keys(m, "id", "type")
            if not ok:
                issues.append(f"member[{i}]: {detail}")
                continue
            if m.get("type") not in ("USER", "GROUP"):
                issues.append(f"member[{i}]: type must be USER or GROUP, got '{m.get('type')}'")

        check(
            "All members have valid shape",
            len(issues) == 0,
            f"\n" + "\n".join(f"       · {i}" for i in issues) if issues else ""
        )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate a running Content Gateway server against the Moveworks schema.")
    parser.add_argument("--rebac", action="store_true",
                        help="Also validate /v1/users, /v1/groups, and /v1/files/{id}/permissions (required for ReBAC)")
    args = parser.parse_args()

    if not API_KEY:
        print(f"\n{FAIL} GATEWAY_API_KEY is not set.")
        print("  Export it before running: export GATEWAY_API_KEY=your-key\n")
        sys.exit(1)

    print(f"\nMoveworks Content Gateway: Schema Validator")
    print(f"{'═' * 44}")
    print(f"  Server:  {SERVER_URL}")
    print(f"  Mode:    {'ReBAC (full)' if args.rebac else 'Files only  (add --rebac to test users, groups, permissions)'}")

    validate_auth()
    files = validate_files()
    validate_single_file(files)

    if args.rebac:
        validate_permissions_metadata()
        validate_permissions(files)
        validate_users()
        validate_groups()

    print(f"\n{'═' * 44}")
    if errors_found == 0:
        print(f"  {PASS} All checks passed\n")
    else:
        print(f"  {FAIL} {errors_found} check(s) failed. Fix the issues above before connecting Moveworks\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
