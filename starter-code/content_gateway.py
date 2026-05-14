"""
Moveworks Content Gateway: Starter Server
══════════════════════════════════════════════════════════════════
This file is both a working demo and your integration starting point.

STEP 1: RUN IT NOW
  python content_gateway.py
  The built-in sample data (Acme IT Knowledge Portal) demonstrates every
  supported content type, permission pattern, and group structure. Use it
  to verify your Moveworks connector is wired up before touching any code.

STEP 2: CONNECT YOUR SOURCE
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

  OData pagination, Bearer auth, and error shapes are complete and do not need
  changes. The rate-limit header hook (`add_rate_limit_headers`) is in place
  but the values are commented out by default. Wire them up to your real
  rate-limit budget when you go to production.

Full API spec:  https://docs.moveworks.com/api-reference/content-gateway/content-gateway
Deploy guide:   https://docs.moveworks.com/api-reference/content-gateway/starter-code

KEY FIELD TO GET RIGHT
  `last_modified_datetime` on each file (returned by map_item_to_node) is the
  cache fingerprint Moveworks uses to skip re-downloading unchanged file
  binaries on subsequent syncs. An accurate, monotonically-updated value is the
  primary way to keep ongoing ingestion load low. See the map_item_to_node
  docstring for detail.

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
# All secrets are read from environment variables. Never hardcode them here.
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

# ── Auth: uncomment the block that matches your source system ────────────────
# _source_headers() is called by every fetch function. One change here
# applies everywhere. You never need to touch the fetch functions for auth.
# Only one block should be active at a time.

# BEARER TOKEN (most common; sends Authorization: Bearer <token>)
def _source_headers() -> dict:
    return {"Authorization": f"Bearer {SOURCE_API_KEY}"}

# API KEY HEADER: a static key sent in a named header
# API_KEY_HEADER = "X-API-Key"  # TODO: your header name (e.g. X-API-Key, Api-Key, X-Auth-Token)
# def _source_headers() -> dict:
#     return {API_KEY_HEADER: SOURCE_API_KEY}

# OAUTH 2.0 CLIENT CREDENTIALS: exchanges client ID + secret for a short-lived token
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

# NO AUTH: open API, no credentials required
# def _source_headers() -> dict:
#     return {}


# ============================================================
# SECTION 2: SOURCE FUNCTIONS
# ============================================================
# Implement the fetch_* functions below to call your source API.
# These are the only functions you need to write. Everything else
# is handled by the gateway server in Section 4: #
# Each function has a docstring explaining what to return and what
# patterns to watch for. When SOURCE_API_BASE_URL is not set, these
# functions return sample data so you can run the server immediately.

# --- Sample data (used in demo mode only. Safe to delete once you connect a real source) ---
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
        "title": "Board Meeting Deck. April 2026",
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

# Five permission patterns are demonstrated below. Covering the most common
# real-world scenarios a Content Gateway integration will encounter:
#
#   PUBLIC (*)        Group id "*" means every user can see the document.
#                     Use this when a document has no access restrictions.
#
#   ALL_EMPLOYEES     A top-level group that contains nested sub-groups.
#                     John is in group-it-staff, which is a member of
#                     group-all-employees, so he inherits access here.
#                     Moveworks resolves nesting automatically. You only
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
    functions you will spend the most time on. It is entirely yours to implement.

    Returns:
        (items, has_more)
          items:    List of raw document dicts from your API. The shape only
                    matters in map_item_to_node(). Return whatever your API gives you.
          has_more: True if there are more pages after this one.

    MULTI-SOURCE SYSTEMS (SharePoint, Confluence, Google Drive, Zendesk, ...):
    Most enterprise content systems organize content across multiple containers -
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
        fetch_file_from_source() instead. No download is needed.

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
      {"type": "USER" | "GROUP", "id": "<id>", "action": "VIEW"}

    Only "VIEW" is currently supported as an action. Other values are rejected
    by the schema validator.

    PERMISSION INHERITANCE (SharePoint, Confluence, Box, Google Drive, ...):
    Many systems do not store permissions on individual documents. Instead, a
    document inherits its access rules from the folder, space, or site that
    contains it. You resolve the effective permissions and return them as a
    flat list.

    PERFORMANCE (IMPORTANT FOR LARGE CORPORA):
    This function is called once per file per sync. Walking the inheritance
    hierarchy with live API calls (2-4 calls per document) multiplies your
    first-sync load by the same factor. For a 10,000-file corpus that's
    20,000-40,000 extra calls to your source system on every sync.

    Strongly prefer bulk pre-fetching when your source supports it:

        _PERMISSION_CACHE: dict[str, list[dict]] = {}

        def _ensure_permissions_loaded():
            if _PERMISSION_CACHE:
                return
            # One bulk call (or a small handful) to your source instead of one per file
            for acl in requests.get(f"{BASE}/all-acls").json():
                _PERMISSION_CACHE[acl["doc_id"]] = _map_acl_entries(acl["entries"])

        def fetch_permissions_for_file(file_id: str) -> list[dict]:
            _ensure_permissions_loaded()
            return _PERMISSION_CACHE.get(file_id, [{"type": "GROUP", "id": "*", "action": "VIEW"}])

    Only fall back to per-file live calls when your source has no bulk-fetch
    capability. And in that case, be deliberate about the per-document call
    count, because it directly multiplies first-sync duration.

    If your content is fully public (no per-document access control), return:
        return [{"type": "GROUP", "id": "*", "action": "VIEW"}]

    The return signature does not change regardless of how you resolve the
    permissions. Moveworks always receives the same flat list.

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
    here and flatten before returning. Same pattern as fetch_files_from_source:

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
    Fetch the DIRECT members of a specific group. Users and/or sub-groups.

    Moveworks handles nested group resolution at query time. Return only the
    direct members of `group_id`, not transitive descendants. If group A
    contains group B which contains user U, the response for group A is
    [{"type": "GROUP", "id": "B"}], NOT [{"type": "USER", "id": "U"}].

    Returns:
        (members, has_more)
        Each member should be a dict with keys: type ("USER" or "GROUP"), id, name

    PAGINATION (IMPORTANT FOR LARGE GROUPS):
    Respect the `skip` and `top` parameters and return `has_more=True` when
    there are more members beyond the current page. The starter handler emits
    `@odata.nextLink` based on your `has_more` value, and Moveworks follows
    the chain automatically.

    This matters most for groups with very large membership counts (e.g., an
    "all employees" group with tens of thousands of members). Returning every
    member in a single response produces a slow, oversized payload that risks
    hitting response-time limits. Paginate by honoring `top`.

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

def map_item_to_node(item: dict, *, include_html_body: bool = False) -> dict:
    """
    Map a raw document from your source API to a Content Gateway Node.

    Required fields: id, name, external_url, last_modified_datetime, content.mime_type
    Optional fields: size, status, created_datetime, created_by, last_modified_by, custom_attributes

    Supported MIME types:
        application/pdf
        application/vnd.openxmlformats-officedocument.wordprocessingml.document  (.docx)
        application/vnd.openxmlformats-officedocument.presentationml.presentation (.pptx)
        text/plain
        text/html  (inline HTML body. Fetched via /files/{id})

    `last_modified_datetime` is special: Moveworks uses it as a cache fingerprint
    for the file's BINARY content. On subsequent syncs, files whose timestamp
    matches the previously cached value skip the /files/{id}/download call
    entirely. Returning an accurate, monotonically-updated value is the primary
    way to keep ongoing ingestion load low. Especially for large attachments.

    Note: the cache applies only to binary downloads. HTML files (mime_type ==
    "text/html") have their body fetched via /files/{id} on every sync, with
    no equivalent caching. If your corpus is mostly HTML, ongoing load will
    be roughly the same as first-sync load.

    `include_html_body` controls whether HTML body content is embedded in the
    response. Default is False (used by the /files list endpoint, where
    Moveworks does not read body). The /files/{id} endpoint sets this to True
    so the body comes back inline. Including body unconditionally is wasted
    payload on every list response.

    `size` (optional but recommended): the file size in bytes. Moveworks
    currently caps individual file content at 25 MB. Files larger than that
    are downloaded but then rejected by the indexing pipeline (status
    FILE_SIZE_LIMIT_EXCEEDED) and never appear in search. Returning an accurate
    `size` lets future optimizations avoid the wasted download.

    TODO: Update each field mapping to match your source API's response shape.
    The field names on the right (item["title"], item["url"], etc.) are examples -
    replace them with whatever your API actually returns.
    """
    mime_type = item.get("mime_type", "application/pdf")      # TODO: your MIME type field

    content: dict = {
        "mime_type": mime_type,                               # required
        "size": item.get("file_size"),                        # optional. Bytes; helps with 25MB cap
    }

    if mime_type == "text/html":
        # HTML body is read by Moveworks from the /files/{id} response, not
        # from the /files list response. Only include body when this mapper
        # is called for the single-file endpoint.
        if include_html_body:
            content["body"] = item.get("html_body", "")      # TODO: your HTML body field
    else:
        content["download_path"] = f"/{item.get('id', '')}/download"  # TODO: your ID field
        content["sha1_hash"] = item.get("sha1_hash")          # optional. For dedup

    return {
        "id": str(item["id"]),                               # required. Stable unique ID
        "name": item["title"],                               # required. TODO: your title field
        "external_url": item["url"],                         # required. TODO: the URL users click
        "last_modified_datetime": item["updated_at"],        # required. TODO: ISO 8601 timestamp
        "status": "deleted" if item.get("archived") else "active",  # TODO: your archive/status logic
        "created_datetime": item.get("created_at"),          # optional
        "created_by": item.get("author_email"),              # optional
        "last_modified_by": item.get("last_editor_email"),   # optional
        "content": content,
        "custom_attributes": {},                             # optional. Add any extra metadata here
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
        return  # GATEWAY_API_KEY not set. Skipping auth (useful for local dev)

    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token != GATEWAY_API_KEY:
        return _error_response(401, "AUTHENTICATION_FAILED", "Bearer token missing or invalid.")


@app.after_request
def add_rate_limit_headers(response: Response) -> Response:
    # Rate-limit headers are how you tell Moveworks how fast it can call your
    # gateway. Moveworks reads these headers on every response and proactively
    # slows down its call rate when your remaining capacity drops below ~30% -
    # no need to wait until you have to return a 429.
    #
    # IMPORTANT: emitting static placeholder values is worse than emitting
    # nothing at all. If you advertise "599 of 600 remaining" on every response,
    # Moveworks reads "plenty of headroom" and never slows down. Even when
    # your backend is overloaded. The headers are deliberately commented out
    # below so a default deployment doesn't accidentally advertise unlimited
    # capacity.
    #
    # When you DO have a real rate limit (Flask-Limiter, AWS API Gateway
    # throttling, source-system quota, etc.), uncomment the lines below and
    # update the values per response to reflect your actual current capacity.
    # Common header-name variants (`X-Rate-Limit-*`, `RateLimit-*` per RFC 9456)
    # are also recognized.

    # response.headers["X-RateLimit-Limit"]     = str(your_per_minute_limit)
    # response.headers["X-RateLimit-Remaining"] = str(your_remaining_budget)
    # response.headers["X-RateLimit-Reset"]     = str(seconds_until_reset)
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
        # HTML body is intentionally omitted from list responses. Moveworks
        # re-fetches it via /files/{id}. See map_item_to_node docstring.
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
        "value": map_item_to_node(item, include_html_body=True),
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
