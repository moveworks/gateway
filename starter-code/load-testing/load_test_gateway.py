"""
Moveworks Content Gateway — Load Testing Server
════════════════════════════════════════════════
This server generates synthetic documents at scale to stress-test Moveworks'
content ingestion pipeline. It is NOT a real integration starting point.

Use it to verify that your Moveworks environment can handle your expected
document volume and file size distribution before connecting a real source.

CONFIGURATION
─────────────
  _FILE_LIMIT             Total number of synthetic documents to generate (default: 50,000)
  _FILE_NAME_TO_PROPORTION  Distribution of file sizes across the document set
  _SET_TO_CURRENT_TIME    Set True to use live timestamps; False for fixed timestamps

USAGE
─────
  pip install flask
  python load_test_gateway.py

  The server starts on port 5001. Point your Moveworks Content Gateway
  connector at it and trigger a sync to observe ingestion behavior at scale.

NOTE: This server implements /v1/files only — no users, groups, or permissions.
All documents use a public dummy PDF as the download target.
For a full reference implementation with users, groups, and permissions,
see content_gateway.py in the parent directory.
"""

import base64
from datetime import datetime, timezone
from typing import List, Dict, Tuple
import os

from flask import Flask, make_response, request, Response, jsonify, send_from_directory, Blueprint

app = Flask(__name__)
files_bp = Blueprint("files", __name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_DEFAULT_PAGE_SIZE = 1000
_FILE_LIMIT = 50000

# Adjust proportions to match your real content distribution.
# Values must sum to 1.0.
_FILE_NAME_TO_PROPORTION = {
    "150_kb.pdf": 0.20,
    "500_kb.pdf": 0.20,
    "1_mb.pdf":   0.20,
    "5_mb.pdf":   0.20,
    "10_mb.pdf":  0.15,
    "100_mb.pdf": 0.05,
}

_NEXT_URL_FORMAT = "{base}v1/files?$skip={offset}&$top={page_size}&$filter={filter}"

# Set True to use the current timestamp on every response (useful for testing
# incremental sync behavior). False uses fixed timestamps for reproducibility.
_SET_TO_CURRENT_TIME = False

# ── Auth (disabled by default) ────────────────────────────────────────────────
# Uncomment and configure if your test environment requires authentication.

# _JWT_TOKEN = "some_jwt_token"
# _CLIENT_ID = "some_client_id"
# _CLIENT_SECRET = "some_client_secret"

# @files_bp.before_request
# def validate_auth():
#     authorization = request.headers.get("Authorization")
#     if not authorization:
#         return create_error_response(401, "AUTHENTICATION_FAILED", "Authorization header missing.")
#     token = authorization.replace("Bearer ", "")
#     if not token or token != _JWT_TOKEN:
#         return create_error_response(401, "AUTHENTICATION_FAILED", "Bearer token missing or invalid.")

# ── Helpers ───────────────────────────────────────────────────────────────────

def create_error_response(http_code: int, code: str, message: str) -> Response:
    return make_response({"code": code, "message": message}, http_code)

# ── Routes ────────────────────────────────────────────────────────────────────

@files_bp.route("/files", methods=["GET"])
def get_files() -> Response:
    page_size = request.args.get(key="$top", default=_DEFAULT_PAGE_SIZE, type=int)
    offset = request.args.get(key="$skip", default=0, type=int)
    filter_param = request.args.get(key="$filter", default="", type=str)

    files, next_url = list_files(offset, page_size, filter_param)
    return make_response({"value": files, "@odata.nextLink": next_url, "@odata.context": request.url}, 200)


def list_files(offset: int, page_size: int, filter_param: str) -> Tuple[List[Dict], str]:
    files_count = {
        file_name: int(page_size * proportion)
        for file_name, proportion in _FILE_NAME_TO_PROPORTION.items()
    }

    files_to_return = []
    current_index = offset + 1
    for file_name, count in files_count.items():
        for _ in range(count):
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            file_name_with_index = f"{current_index}_{file_name}"
            file_id = base64.b64encode(file_name_with_index.encode()).decode()
            files_to_return.append({
                "id": file_id,
                "name": file_name_with_index,
                "status": "active",
                "last_modified_datetime": current_time if _SET_TO_CURRENT_TIME else "2023-04-17T12:34:56Z",
                "created_datetime":       current_time if _SET_TO_CURRENT_TIME else "2023-01-01T00:00:00Z",
                "content": {
                    "download_path": f"{file_id}/download",
                    "mime_type": "application/pdf",
                },
                "external_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
            })
            current_index += 1

    new_offset = min(offset + page_size, _FILE_LIMIT)
    next_url = (
        _NEXT_URL_FORMAT.format(base=request.url_root, offset=new_offset, page_size=page_size, filter=filter_param)
        if new_offset < _FILE_LIMIT else ""
    )
    return files_to_return, next_url


@files_bp.route("/files/<file_id>", methods=["GET"])
def get_file_metadata(file_id: str) -> Response:
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    encoded_id = base64.b64encode(file_id.encode()).decode()
    file_metadata = {
        "id": encoded_id,
        "name": file_id,
        "status": "active",
        "last_modified_datetime": current_time if _SET_TO_CURRENT_TIME else "2023-04-17T12:34:56Z",
        "created_datetime":       current_time if _SET_TO_CURRENT_TIME else "2023-01-01T00:00:00Z",
        "content": {
            "download_path": f"{encoded_id}/download",
            "mime_type": "application/pdf",
        },
        "external_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
    }
    return make_response({"value": file_metadata, "@odata.context": request.url}, 200)


@files_bp.route("/files/<file_id>/download", methods=["GET"])
def download_file(file_id: str) -> Response:
    directory_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample-content")

    # IDs are base64 of "<index>_<sample file name>", e.g. "1_150_kb.pdf" → serve "150_kb.pdf".
    try:
        decoded = base64.b64decode(file_id, validate=True).decode()
    except ValueError:
        return create_error_response(400, "INVALID_FILE_ID", f"File ID {file_id} is not valid base64.")
    filename = decoded.split("_", 1)[-1]

    if not os.path.isfile(os.path.join(directory_path, filename)):
        return create_error_response(404, "FILE_NOT_FOUND", f"File {filename} not found in {directory_path}.")

    return send_from_directory(directory_path, filename, as_attachment=True, mimetype="application/octet-stream")


@app.route("/", methods=["GET"])
def index() -> Response:
    sample_name = f"1_{next(iter(_FILE_NAME_TO_PROPORTION))}"
    sample_id = base64.b64encode(sample_name.encode()).decode()
    endpoints = [
        ("/v1/files", "List files (first page)"),
        ("/v1/files?$top=10", "List files (10 per page)"),
        ("/v1/files?$skip=1000&$top=10", "List files (paginated, offset 1000)"),
        (f"/v1/files/{sample_name}", "File metadata (sample)"),
        (f"/v1/files/{sample_id}/download", "File download (sample)"),
    ]
    items = "".join(f'<li><a href="{path}">{path}</a> — {desc}</li>' for path, desc in endpoints)
    return make_response(
        f"<h1>Content Gateway — Load Testing Server</h1>"
        f"<p>Generating {_FILE_LIMIT:,} synthetic documents.</p>"
        f"<ul>{items}</ul>",
        200,
    )


app.register_blueprint(files_bp, url_prefix="/v1")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
