"""
Moveworks Content Gateway — Starter Server
══════════════════════════════════════════════════════════════════
This file is both a working demo and your integration starting point.

STEP 1 — RUN IT NOW
  python content_gateway.py
  The built-in sample data (Acme IT Knowledge Portal) demonstrates every
  supported content type, permission pattern, and group structure. Use it
  to verify your Moveworks connector is wired up before touching any code.

STEP 2 — CONNECT YOUR SOURCE
  Edit the three labeled sections in this file:

  SECTION 1 · CONFIGURATION
    Set SOURCE_API_BASE_URL and uncomment the _source_headers() block
    that matches your auth method (Bearer, API key, OAuth2, or none).

  SECTION 2 · SOURCE FUNCTIONS  ←  this is where you spend your time
    Implement the fetch_* functions to call your source API.
    Each function has a docstring explaining what to return and what
    patterns to watch for (multi-source enumeration, permission inheritance).

  SECTION 3 · MAPPER FUNCTIONS
    Update the field names in map_item_to_node (and map_item_to_user,
    map_item_to_group if you sync identity) to match your API's response shape.

  Everything else — OData pagination, Bearer auth, error shapes, rate-limit
  headers — is complete and does not need changes.

Full API spec:  https://help.moveworks.com/api-reference/content-gateway/content-gateway
Deploy guide:   https://help.moveworks.com/api-reference/content-gateway/starter-code

Deployment:
  - Local dev:       python content_gateway.py  (port 5001 by default)
  - Heroku / VM:     run directly; set PORT env var to override
  - AWS Lambda:      wrap with a WSGI adapter (e.g. mangum)
  - Azure Functions: wrap with a WSGI middleware (e.g. azure-functions-wsgi)
"""

import hashlib
import os
from typing import Optional

import requests
from flask import Flask, Blueprint, jsonify, make_response, request, Response

app = Flask(__name__)
files_bp = Blueprint("files", __name__)
users_bp = Blueprint("users", __name__)
groups_bp = Blueprint("groups", __name__)


# ============================================================
# SECTION 1: CONFIGURATION
# ============================================================
# All secrets are read from environment variables — never hardcode them here.
#
# How to set these depends on your deployment platform:
#   AWS Lambda:      Secrets Manager or Lambda Environment Variables
#   Azure Functions: Key Vault or App Settings
#   Heroku:          Config Vars (heroku config:set KEY=value)
#   Local dev:       Copy .env.example to .env and fill in values,
#                    then load with: export $(cat .env | xargs)

# The API key Moveworks will send to authenticate to THIS gateway.
# Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "")

# Your content source system credentials.
SOURCE_API_BASE_URL = os.environ.get("SOURCE_API_BASE_URL", "")  # TODO: your system's base URL
SOURCE_API_KEY      = os.environ.get("SOURCE_API_KEY", "")       # TODO: your system's API key

DEFAULT_PAGE_SIZE = 50

# When SOURCE_API_BASE_URL is not set, the server runs in demo mode using
# hardcoded sample data. This lets you verify all endpoints work before
# connecting a real source system.
DEMO_MODE = not bool(SOURCE_API_BASE_URL)

# ── Auth — uncomment the block that matches your source system ────────────────
# _source_headers() is called by every fetch function. One change here
# applies everywhere — you never need to touch the fetch functions for auth.
# Only one block should be active at a time.

# BEARER TOKEN (most common — sends Authorization: Bearer <token>)
def _source_headers() -> dict:
    return {"Authorization": f"Bearer {SOURCE_API_KEY}"}

# API KEY HEADER — a static key sent in a named header
# API_KEY_HEADER = "X-API-Key"  # TODO: your header name (e.g. X-API-Key, Api-Key, X-Auth-Token)
# def _source_headers() -> dict:
#     return {API_KEY_HEADER: SOURCE_API_KEY}

# OAUTH 2.0 CLIENT CREDENTIALS — exchanges client ID + secret for a short-lived token
# SOURCE_CLIENT_ID     = os.environ.get("SOURCE_CLIENT_ID", "")
# SOURCE_CLIENT_SECRET = os.environ.get("SOURCE_CLIENT_SECRET", "")
# TOKEN_URL            = "https://your-system.example.com/oauth/token"  # TODO: your token endpoint
# _token_cache: dict   = {}
# def _source_headers() -> dict:
#     import time
#     now = time.time()
#     if _token_cache.get("expires_at", 0) > now + 60:
#         return {"Authorization": f"Bearer {_token_cache['token']}"}
#     resp = requests.post(TOKEN_URL, data={
#         "grant_type": "client_credentials",
#         "client_id": SOURCE_CLIENT_ID,
#         "client_secret": SOURCE_CLIENT_SECRET,
#     }, timeout=10)
#     resp.raise_for_status()
#     data = resp.json()
#     _token_cache["token"] = data["access_token"]
#     _token_cache["expires_at"] = now + data.get("expires_in", 3600)
#     return {"Authorization": f"Bearer {_token_cache['token']}"}

# NO AUTH — open API, no credentials required
# def _source_headers() -> dict:
#     return {}


# ============================================================
# SECTION 2: SOURCE FUNCTIONS
# ============================================================
# Implement the fetch_* functions below to call your source API.
# These are the only functions you need to write — everything else
# is handled by the gateway server in Section 4.
#
# Each function has a docstring explaining what to return and what
# patterns to watch for. When SOURCE_API_BASE_URL is not set, these
# functions return sample data so you can run the server immediately.

# --- Sample data (used in demo mode only — safe to delete once you connect a real source) ---
# Theme: Acme Corp IT Knowledge Portal
# John (john.m@acmecorp.internal) is in group-it-staff and group-all-employees (via nesting).
# He does NOT have access to kb-008 (hr), kb-009 (executives), or kb-010 (executives).

_SAMPLE_FILES = [
    {
        "id": "kb-001",
        "title": "VPN Setup Guide",
        "url": "https://it.acmecorp.internal/kb/vpn-setup",
        "updated_at": "2026-03-15T09:00:00Z",
        "created_at": "2023-08-01T10:00:00Z",
        "author_email": "it-ops@acmecorp.internal",
        "last_editor_email": "sarah.chen@acmecorp.internal",
        "mime_type": "text/html",
        "html_body": "<h1>VPN Setup Guide</h1><p>Download the <strong>Acme VPN</strong> client from the IT portal at <a href='https://it.acmecorp.internal/downloads'>it.acmecorp.internal/downloads</a>. Enter your Acme SSO credentials when prompted. Contact <a href='mailto:helpdesk@acmecorp.internal'>helpdesk@acmecorp.internal</a> if you encounter MFA issues.</p>",
    },
    {
        "id": "kb-002",
        "title": "IT Security Policy 2026",
        "url": "https://it.acmecorp.internal/policies/security-2026",
        "updated_at": "2026-01-10T14:00:00Z",
        "created_at": "2025-12-01T09:00:00Z",
        "author_email": "ciso@acmecorp.internal",
        "last_editor_email": "sarah.chen@acmecorp.internal",
        "mime_type": "application/pdf",
        "file_size": 389120,
    },
    {
        "id": "kb-003",
        "title": "Helpdesk Password Reset SOP",
        "url": "https://it.acmecorp.internal/kb/password-reset-sop",
        "updated_at": "2026-02-20T11:30:00Z",
        "created_at": "2024-04-15T08:00:00Z",
        "author_email": "sarah.chen@acmecorp.internal",
        "last_editor_email": "john.m@acmecorp.internal",
        "mime_type": "text/plain",
        "file_size": 6144,
    },
    {
        "id": "kb-004",
        "title": "Incident Response Runbook",
        "url": "https://it.acmecorp.internal/kb/incident-response-runbook",
        "updated_at": "2026-04-01T16:45:00Z",
        "created_at": "2024-01-20T09:00:00Z",
        "author_email": "john.m@acmecorp.internal",
        "last_editor_email": "john.m@acmecorp.internal",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "file_size": 114688,
    },
    {
        "id": "kb-005",
        "title": "Q2 2026 Company All-Hands Slides",
        "url": "https://it.acmecorp.internal/presentations/q2-2026-all-hands",
        "updated_at": "2026-04-14T10:00:00Z",
        "created_at": "2026-04-13T18:00:00Z",
        "author_email": "comms@acmecorp.internal",
        "last_editor_email": "comms@acmecorp.internal",
        "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "file_size": 6291456,
    },
    {
        "id": "kb-006",
        "title": "Network Architecture Reference Guide",
        "url": "https://it.acmecorp.internal/kb/network-architecture",
        "updated_at": "2026-03-05T13:00:00Z",
        "created_at": "2023-11-01T09:00:00Z",
        "author_email": "netops@acmecorp.internal",
        "last_editor_email": "john.m@acmecorp.internal",
        "mime_type": "application/pdf",
        "file_size": 2097152,
    },
    {
        "id": "kb-007",
        "title": "New Employee IT Onboarding Checklist",
        "url": "https://it.acmecorp.internal/kb/it-onboarding",
        "updated_at": "2026-02-01T09:00:00Z",
        "created_at": "2023-05-10T08:00:00Z",
        "author_email": "hr@acmecorp.internal",
        "last_editor_email": "sarah.chen@acmecorp.internal",
        "mime_type": "text/plain",
        "file_size": 8192,
    },
    {
        "id": "kb-008",
        "title": "Salary Bands & Compensation Review 2026",
        "url": "https://hr.acmecorp.internal/compensation/salary-bands-2026",
        "updated_at": "2026-03-01T09:00:00Z",
        "created_at": "2026-02-15T08:00:00Z",
        "author_email": "marcus.obi@acmecorp.internal",
        "last_editor_email": "marcus.obi@acmecorp.internal",
        "mime_type": "application/pdf",
        "file_size": 471040,
    },
    {
        "id": "kb-009",
        "title": "Meridian Acquisition Due Diligence Summary",
        "url": "https://exec.acmecorp.internal/ma/meridian-diligence",
        "updated_at": "2026-04-22T15:00:00Z",
        "created_at": "2026-04-10T09:00:00Z",
        "author_email": "diana.reeves@acmecorp.internal",
        "last_editor_email": "diana.reeves@acmecorp.internal",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "file_size": 163840,
    },
    {
        "id": "kb-010",
        "title": "Board Meeting Deck — April 2026",
        "url": "https://exec.acmecorp.internal/board/april-2026-deck",
        "updated_at": "2026-04-28T08:00:00Z",
        "created_at": "2026-04-25T10:00:00Z",
        "author_email": "diana.reeves@acmecorp.internal",
        "last_editor_email": "diana.reeves@acmecorp.internal",
        "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "file_size": 8388608,
    },
]

_SAMPLE_FILES_BY_ID = {f["id"]: f for f in _SAMPLE_FILES}

_SAMPLE_USERS = [
    {"id": "user-001", "email": "sarah.chen@acmecorp.internal",   "display_name": "Sarah Chen",    "active": True, "updated_at": "2024-01-01T00:00:00Z"},
    {"id": "user-002", "email": "marcus.obi@acmecorp.internal",   "display_name": "Marcus Obi",    "active": True, "updated_at": "2024-01-01T00:00:00Z"},
    {"id": "user-003", "email": "diana.reeves@acmecorp.internal", "display_name": "Diana Reeves",  "active": True, "updated_at": "2024-01-01T00:00:00Z"},
    {"id": "user-004", "email": "john.m@acmecorp.internal",      "display_name": "John M",        "active": True, "updated_at": "2024-01-01T00:00:00Z"},
    {"id": "user-005", "email": "priya.nair@acmecorp.internal",   "display_name": "Priya Nair",    "active": True, "updated_at": "2024-01-01T00:00:00Z"},
]

_SAMPLE_GROUPS = [
    {"id": "group-it-staff",      "name": "IT Staff",      "updated_at": "2024-01-01T00:00:00Z"},
    {"id": "group-all-employees", "name": "All Employees", "updated_at": "2024-01-01T00:00:00Z"},
    {"id": "group-hr",            "name": "HR",            "updated_at": "2024-01-01T00:00:00Z"},
    {"id": "group-executives",    "name": "Executives",    "updated_at": "2024-01-01T00:00:00Z"},
]

_SAMPLE_GROUP_MEMBERS: dict[str, list[dict]] = {
    "group-it-staff": [
        {"type": "USER", "id": "user-001", "name": "Sarah Chen"},
        {"type": "USER", "id": "user-004", "name": "John M"},
    ],
    "group-all-employees": [
        {"type": "GROUP", "id": "group-it-staff", "name": "IT Staff"},
        {"type": "USER",  "id": "user-002",       "name": "Marcus Obi"},
        {"type": "USER",  "id": "user-003",       "name": "Diana Reeves"},
        {"type": "USER",  "id": "user-005",       "name": "Priya Nair"},
    ],
    "group-hr": [
        {"type": "USER", "id": "user-002", "name": "Marcus Obi"},
        {"type": "USER", "id": "user-005", "name": "Priya Nair"},
    ],
    "group-executives": [
        {"type": "USER", "id": "user-003", "name": "Diana Reeves"},
    ],
}

# Five permission patterns are demonstrated below — covering the most common
# real-world scenarios a Content Gateway integration will encounter:
#
#   PUBLIC (*)        Group id "*" means every user can see the document.
#                     Use this when a document has no access restrictions.
#
#   ALL_EMPLOYEES     A top-level group that contains nested sub-groups.
#                     John is in group-it-staff, which is a member of
#                     group-all-employees, so he inherits access here.
#                     Moveworks resolves nesting automatically — you only
#                     need to return direct members from each group endpoint.
#
#   IT_STAFF          Department-scoped grant. John is a direct member, so
#                     he sees these documents.
#
#   HR / EXECUTIVES   John is not in either group, so these documents are
#                     hidden from him in search results. This is the ReBAC
#                     (resource-based access control) model in action.
#
# In a real integration, fetch_permissions_for_file() calls your permission
# API and maps its response to this same {"type", "id", "action"} shape.
_SAMPLE_PERMISSIONS: dict[str, list[dict]] = {
    "kb-001": [{"type": "GROUP", "id": "*",                   "action": "VIEW"}],  # public
    "kb-002": [{"type": "GROUP", "id": "group-all-employees", "action": "VIEW"}],  # John ✓ (via it-staff)
    "kb-003": [{"type": "GROUP", "id": "group-it-staff",      "action": "VIEW"}],  # John ✓
    "kb-004": [{"type": "GROUP", "id": "group-it-staff",      "action": "VIEW"}],  # John ✓
    "kb-005": [{"type": "GROUP", "id": "group-all-employees", "action": "VIEW"}],  # John ✓ (via it-staff)
    "kb-006": [{"type": "GROUP", "id": "group-it-staff",      "action": "VIEW"}],  # John ✓
    "kb-007": [{"type": "GROUP", "id": "group-all-employees", "action": "VIEW"}],  # John ✓ (via it-staff)
    "kb-008": [{"type": "GROUP", "id": "group-hr",            "action": "VIEW"}],  # John ✗
    "kb-009": [{"type": "GROUP", "id": "group-executives",    "action": "VIEW"}],  # John ✗
    "kb-010": [{"type": "GROUP", "id": "group-executives",    "action": "VIEW"}],  # John ✗
}

# --- End of sample data ---


def fetch_files_from_source(skip: int, top: int) -> tuple[list[dict], bool]:
    """
    Fetch a page of documents from your source system. This is one of the two
    functions you will spend the most time on — it is entirely yours to implement.

    Returns:
        (items, has_more)
          items:    List of raw document dicts from your API. The shape only
                    matters in map_item_to_node() — return whatever your API gives you.
          has_more: True if there are more pages after this one.

    MULTI-SOURCE SYSTEMS (SharePoint, Confluence, Google Drive, Zendesk, ...):
    Most enterprise content systems organize content across multiple containers —
    SharePoint has sites, Confluence has spaces, Google Drive has shared drives,
    Zendesk has brands. The Content Gateway expects a single flat stream of
    documents. If that describes your system, enumerate all containers here and
    flatten before returning:

        def fetch_files_from_source(skip, top):
            all_items = []
            for container in _get_all_containers():   # sites, spaces, drives...
                all_items.extend(_get_items_from_container(container["id"]))
            page = all_items[skip:skip + top]
            return page, (skip + len(page)) < len(all_items)

    The same pattern applies to fetch_users_from_source and
    fetch_groups_from_source if your identity data spans multiple directories.

    TODO: Replace the DEMO_MODE block below with a call to your actual API.
    """
    if DEMO_MODE:
        page = _SAMPLE_FILES[skip : skip + top]
        return page, (skip + len(page)) < len(_SAMPLE_FILES)

    response = requests.get(
        f"{SOURCE_API_BASE_URL}/documents",                   # TODO: your list documents endpoint
        headers=_source_headers(),
        params={
            "offset": skip,                                   # TODO: your pagination offset param
            "limit": top,                                     # TODO: your page size param
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    items = data.get("documents", [])                         # TODO: your response list key
    total = data.get("total", 0)                              # TODO: your total count key
    return items, (skip + len(items)) < total


def fetch_file_from_source(file_id: str) -> Optional[dict]:
    """
    Fetch metadata for a single document from your content system.

    Returns the raw dict from your API, or None if the document does not exist.

    TODO: Replace the DEMO_MODE block below with a call to your actual API.
    """
    if DEMO_MODE:
        return _SAMPLE_FILES_BY_ID.get(file_id)

    response = requests.get(
        f"{SOURCE_API_BASE_URL}/documents/{file_id}",         # TODO: your single-document endpoint
        headers=_source_headers(),
        timeout=30,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def fetch_file_bytes_from_source(file_id: str) -> Optional[tuple[bytes, str]]:
    """
    Download the binary content of a file from your content system.

    Returns (file_bytes, mime_type), or None if not found.

    Notes:
      - Only needed for non-HTML content (PDF, DOCX, PPTX, TXT).
      - For HTML content, Moveworks reads the `body` field from
        fetch_file_from_source() instead — no download is needed.

    TODO: Replace the DEMO_MODE block below with a call to your actual download endpoint.
    """
    if DEMO_MODE:
        item = _SAMPLE_FILES_BY_ID.get(file_id)
        if item is None:
            return None
        placeholder = f"[Demo] Binary content for: {item['title']}".encode()
        return placeholder, item.get("mime_type", "application/octet-stream")

    response = requests.get(
        f"{SOURCE_API_BASE_URL}/documents/{file_id}/download",  # TODO: your download endpoint
        headers=_source_headers(),
        stream=True,
        timeout=60,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    mime_type = response.headers.get("Content-Type", "application/octet-stream")
    return response.content, mime_type


def fetch_permissions_for_file(file_id: str) -> list[dict]:
    """
    Return who can view a specific file. This is entirely yours to implement.

    Returns a list of permission objects:
      {"type": "USER" | "GROUP", "id": "<id>", "action": "VIEW" | "UPDATE"}

    PERMISSION INHERITANCE (SharePoint, Confluence, Box, Google Drive, ...):
    Many systems do not store permissions on individual documents. Instead, a
    document inherits its access rules from the folder, space, or site that
    contains it. You have to walk that hierarchy yourself and return the resolved
    effective permissions. This commonly requires 2-4 API calls per document:

        def fetch_permissions_for_file(file_id: str) -> list[dict]:
            # 1. Get the document to find its parent container
            doc = requests.get(f"{BASE}/documents/{file_id}").json()
            parent_id = doc.get("parent_id")

            # 2. Check if the document has its own ACL
            acl = requests.get(f"{BASE}/documents/{file_id}/acl").json()
            if not acl.get("inherited"):
                return _map_acl_entries(acl["entries"])

            # 3. Fall back to the parent folder/space/site ACL
            parent_acl = requests.get(f"{BASE}/folders/{parent_id}/acl").json()
            return _map_acl_entries(parent_acl["entries"])

    If your content is fully public (no per-document access control), return:
        return [{"type": "GROUP", "id": "*", "action": "VIEW"}]

    The return signature does not change regardless of how many API calls it takes
    to resolve the permissions — Moveworks always receives the same flat list.

    TODO: Replace the DEMO_MODE block below with a call to your permission system.
    """
    if DEMO_MODE:
        return _SAMPLE_PERMISSIONS.get(file_id, [{"type": "GROUP", "id": "*", "action": "VIEW"}])

    # TODO: call your permission API, e.g.:
    #   response = requests.get(f"{SOURCE_API_BASE_URL}/documents/{file_id}/permissions", ...)
    #   return [{"type": p["entity_type"], "id": p["entity_id"], "action": "VIEW"} for p in response.json()]
    return [{"type": "GROUP", "id": "*", "action": "VIEW"}]


def fetch_users_from_source(skip: int, top: int) -> tuple[list[dict], bool]:
    """
    Fetch a page of users from your identity system.

    Only needed if you are implementing user-level access control.
    Moveworks uses this to resolve user identities when checking permissions.

    Returns:
        (users, has_more)

    MULTI-DIRECTORY SYSTEMS (Workday + Azure AD, LDAP + SCIM, ...):
    If your users live in more than one directory, enumerate all directories
    here and flatten before returning — same pattern as fetch_files_from_source:

        def fetch_users_from_source(skip, top):
            all_users = []
            for directory in _get_all_directories():
                all_users.extend(_get_users_from_directory(directory["id"]))
            page = all_users[skip:skip + top]
            return page, (skip + len(page)) < len(all_users)

    TODO: Replace the DEMO_MODE block below with a call to your user directory.
    If you are not implementing per-user permissions, you can leave this returning ([], False).
    """
    if DEMO_MODE:
        page = _SAMPLE_USERS[skip : skip + top]
        return page, (skip + len(page)) < len(_SAMPLE_USERS)

    # TODO: call your user directory (LDAP, Workday, Azure AD, etc.)
    return [], False


def fetch_groups_from_source(skip: int, top: int) -> tuple[list[dict], bool]:
    """
    Fetch a page of groups from your identity system.

    Only needed if you are implementing group-based access control.

    Returns:
        (groups, has_more)

    MULTI-DIRECTORY SYSTEMS: If groups span multiple directories or organizational
    units, flatten them here using the same pattern as fetch_files_from_source and
    fetch_users_from_source. Ensure group IDs remain globally unique across
    directories (prefix with a namespace if needed, e.g. "azure:group-123").

    TODO: Replace the DEMO_MODE block below with a call to your group directory.
    """
    if DEMO_MODE:
        page = _SAMPLE_GROUPS[skip : skip + top]
        return page, (skip + len(page)) < len(_SAMPLE_GROUPS)

    # TODO: call your group directory
    return [], False


def fetch_group_members_from_source(
    group_id: str, skip: int, top: int
) -> tuple[list[dict], bool]:
    """
    Fetch direct members (users or sub-groups) of a specific group.

    Moveworks handles nested group resolution — you only need to return
    the direct members, not all descendants.

    Returns:
        (members, has_more)
        Each member should be a dict with keys: type ("USER" or "GROUP"), id, name

    TODO: Replace the DEMO_MODE block below with a call to your group membership API.
    """
    if DEMO_MODE:
        all_members = _SAMPLE_GROUP_MEMBERS.get(group_id, [])
        page = all_members[skip : skip + top]
        return page, (skip + len(page)) < len(all_members)

    # TODO: call your group membership API
    return [], False


# ============================================================
# SECTION 3: MAPPER FUNCTIONS
# ============================================================
# These functions transform raw data from your source API into the
# exact shape required by the Content Gateway spec.
#
# Every field marked "required" must always be present and non-null.
# Optional fields improve search quality but will not break ingestion if omitted.

def map_item_to_node(item: dict) -> dict:
    """
    Map a raw document from your source API to a Content Gateway Node.

    Required fields: id, name, external_url, last_modified_datetime, content.mime_type
    Optional fields: status, created_datetime, created_by, last_modified_by, custom_attributes

    Supported MIME types:
        application/pdf
        application/vnd.openxmlformats-officedocument.wordprocessingml.document  (.docx)
        application/vnd.openxmlformats-officedocument.presentationml.presentation (.pptx)
        text/plain
        text/html  (inline HTML body — no download endpoint needed)

    TODO: Update each field mapping to match your source API's response shape.
    The field names on the right (item["title"], item["url"], etc.) are examples —
    replace them with whatever your API actually returns.
    """
    mime_type = item.get("mime_type", "application/pdf")      # TODO: your MIME type field

    content: dict = {
        "mime_type": mime_type,                               # required
        "size": item.get("file_size"),                        # optional — bytes
    }

    if mime_type == "text/html":
        # HTML content is returned inline — no separate download request is needed.
        content["body"] = item.get("html_body", "")          # TODO: your HTML body field
    else:
        content["download_path"] = f"/{item.get('id', '')}/download"  # TODO: your ID field
        content["sha1_hash"] = item.get("sha1_hash")          # optional — for dedup

    return {
        "id": str(item["id"]),                               # required — stable unique ID
        "name": item["title"],                               # required — TODO: your title field
        "external_url": item["url"],                         # required — TODO: the URL users click
        "last_modified_datetime": item["updated_at"],        # required — TODO: ISO 8601 timestamp
        "status": "deleted" if item.get("archived") else "active",  # TODO: your archive/status logic
        "created_datetime": item.get("created_at"),          # optional
        "created_by": item.get("author_email"),              # optional
        "last_modified_by": item.get("last_editor_email"),   # optional
        "content": content,
        "custom_attributes": {},                             # optional — add any extra metadata here
    }


def map_item_to_user(user: dict) -> dict:
    """
    Map a raw user from your identity system to the Content Gateway User schema.

    TODO: Update field mappings to match your identity provider's response shape.
    """
    return {
        "id": str(user["id"]),                               # TODO: your user ID field
        "primary_email_addr": user["email"],                 # TODO: your email field
        "full_name": user.get("display_name", ""),           # TODO: your display name field
        "state": "Active" if user.get("active", True) else "Inactive",
        "last_modified_datetime": user.get("updated_at"),
    }


def map_item_to_group(group: dict) -> dict:
    """
    Map a raw group from your identity system to the Content Gateway Group schema.

    TODO: Update field mappings to match your identity provider's response shape.
    """
    return {
        "id": str(group["id"]),                              # TODO: your group ID field
        "name": group["name"],                               # TODO: your group name field
        "last_modified_datetime": group.get("updated_at"),
    }


def map_item_to_group_member(member: dict) -> dict:
    """
    Map a raw group member to the Content Gateway GroupMember schema.

    TODO: Update field mappings.
    """
    return {
        "type": member.get("type", "USER").upper(),          # "USER" or "GROUP"
        "id": str(member["id"]),
        "name": member.get("name", ""),
    }


# ============================================================
# SECTION 4: GATEWAY SERVER
# ============================================================
# Standard Content Gateway protocol implementation.
# You should not need to edit anything below this line.

def _odata_context_url(entity: str) -> str:
    return f"{request.url_root.rstrip('/')}/$metadata#{entity}"


def _next_link_url(base_path: str, skip: int, top: int) -> str:
    return f"{request.url_root.rstrip('/')}{base_path}?$top={top}&$skip={skip}"


def _error_response(http_code: int, code: str, message: str) -> Response:
    return make_response(jsonify({"error": {"code": code, "message": message}}), http_code)


@app.before_request
def validate_auth():
    if not GATEWAY_API_KEY:
        return  # GATEWAY_API_KEY not set — skipping auth (useful for local dev)

    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token != GATEWAY_API_KEY:
        return _error_response(401, "AUTHENTICATION_FAILED", "Bearer token missing or invalid.")


@app.after_request
def add_rate_limit_headers(response: Response) -> Response:
    # These headers tell Moveworks about your rate limit.
    # TODO: Replace with real values if you are enforcing a rate limit.
    # If you add rate limiting (e.g. Flask-Limiter), update these to reflect actual usage.
    response.headers["X-RateLimit-Limit"] = "600"
    response.headers["X-RateLimit-Remaining"] = "599"
    response.headers["X-RateLimit-Reset"] = "60"
    return response


# --- Files ---

@files_bp.get("/files")
def list_files() -> Response:
    top = request.args.get("$top", DEFAULT_PAGE_SIZE, type=int)
    skip = request.args.get("$skip", 0, type=int)

    try:
        items, has_more = fetch_files_from_source(skip=skip, top=top)
    except requests.HTTPError as e:
        return _error_response(502, "EXTERNAL_REST_ERROR", str(e))

    body: dict = {
        "@odata.context": _odata_context_url("Content"),
        "value": [map_item_to_node(item) for item in items],
    }
    if has_more:
        body["@odata.nextLink"] = _next_link_url("/v1/files", skip + top, top)

    return make_response(jsonify(body), 200)


@files_bp.get("/files/permissions/metadata")
def get_permissions_metadata() -> Response:
    # Only "resource_permission" is supported by Moveworks at this time.
    body = {
        "@odata.context": _odata_context_url("PermissionsMetadata"),
        "model": "resource_permission",
    }
    return make_response(jsonify(body), 200)


@files_bp.get("/files/<file_id>")
def get_file_metadata(file_id: str) -> Response:
    try:
        item = fetch_file_from_source(file_id)
    except requests.HTTPError as e:
        return _error_response(502, "EXTERNAL_REST_ERROR", str(e))

    if item is None:
        return _error_response(404, "NOT_FOUND", f"File {file_id} not found.")

    body = {
        "@odata.context": _odata_context_url("Content"),
        "value": map_item_to_node(item),
    }
    return make_response(jsonify(body), 200)


@files_bp.get("/files/<file_id>/download")
def download_file(file_id: str) -> Response:
    try:
        result = fetch_file_bytes_from_source(file_id)
    except requests.HTTPError as e:
        return _error_response(502, "EXTERNAL_REST_ERROR", str(e))

    if result is None:
        return _error_response(404, "NOT_FOUND", f"File {file_id} not found.")

    file_bytes, mime_type = result
    checksum = hashlib.sha256(file_bytes).hexdigest()

    response = make_response(file_bytes, 200)
    response.headers["Content-Type"] = mime_type
    response.headers["Content-Length"] = str(len(file_bytes))
    response.headers["Checksum-SHA256"] = checksum
    return response


@files_bp.get("/files/<file_id>/permissions")
def get_file_permissions(file_id: str) -> Response:
    top = request.args.get("$top", DEFAULT_PAGE_SIZE, type=int)
    skip = request.args.get("$skip", 0, type=int)

    try:
        all_permissions = fetch_permissions_for_file(file_id)
    except requests.HTTPError as e:
        return _error_response(502, "EXTERNAL_REST_ERROR", str(e))

    page = all_permissions[skip : skip + top]
    body: dict = {
        "@odata.context": _odata_context_url("Permissions"),
        "value": {
            "permissions": page,
            "last_modified_datetime": None,
        },
    }
    if skip + len(page) < len(all_permissions):
        body["@odata.nextLink"] = _next_link_url(f"/v1/files/{file_id}/permissions", skip + top, top)

    return make_response(jsonify(body), 200)


# --- Users ---

@users_bp.get("/users")
def list_users() -> Response:
    top = request.args.get("$top", DEFAULT_PAGE_SIZE, type=int)
    skip = request.args.get("$skip", 0, type=int)

    try:
        users, has_more = fetch_users_from_source(skip=skip, top=top)
    except requests.HTTPError as e:
        return _error_response(502, "EXTERNAL_REST_ERROR", str(e))

    body: dict = {
        "@odata.context": _odata_context_url("Users"),
        "value": [map_item_to_user(u) for u in users],
    }
    if has_more:
        body["@odata.nextLink"] = _next_link_url("/v1/users", skip + top, top)

    return make_response(jsonify(body), 200)


# --- Groups ---

@groups_bp.get("/groups")
def list_groups() -> Response:
    top = request.args.get("$top", DEFAULT_PAGE_SIZE, type=int)
    skip = request.args.get("$skip", 0, type=int)

    try:
        groups, has_more = fetch_groups_from_source(skip=skip, top=top)
    except requests.HTTPError as e:
        return _error_response(502, "EXTERNAL_REST_ERROR", str(e))

    body: dict = {
        "@odata.context": _odata_context_url("Groups"),
        "value": [map_item_to_group(g) for g in groups],
    }
    if has_more:
        body["@odata.nextLink"] = _next_link_url("/v1/groups", skip + top, top)

    return make_response(jsonify(body), 200)


@groups_bp.get("/groups/<group_id>/members")
def list_group_members(group_id: str) -> Response:
    top = request.args.get("$top", DEFAULT_PAGE_SIZE, type=int)
    skip = request.args.get("$skip", 0, type=int)

    try:
        members, has_more = fetch_group_members_from_source(group_id, skip=skip, top=top)
    except requests.HTTPError as e:
        return _error_response(502, "EXTERNAL_REST_ERROR", str(e))

    body: dict = {
        "@odata.context": _odata_context_url("GroupMembers"),
        "value": [map_item_to_group_member(m) for m in members],
    }
    if has_more:
        body["@odata.nextLink"] = _next_link_url(f"/v1/groups/{group_id}/members", skip + top, top)

    return make_response(jsonify(body), 200)


# --- Error handlers ---

@app.errorhandler(400)
def bad_request(e):
    return _error_response(400, "INPUT_VALIDATION_FAILED", str(e))


@app.errorhandler(404)
def not_found(e):
    return _error_response(404, "NOT_FOUND", str(e))


@app.errorhandler(500)
def internal_error(e):
    return _error_response(500, "INTERNAL_SERVER_ERROR", str(e))


# --- Register blueprints ---

app.register_blueprint(files_bp, url_prefix="/v1")
app.register_blueprint(users_bp, url_prefix="/v1")
app.register_blueprint(groups_bp, url_prefix="/v1")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
