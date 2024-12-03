"""Mock Gateway Server"""

import base64
from datetime import datetime, timezone
from typing import List, Dict, Tuple
import os

from flask import Flask, make_response, request, Response, jsonify, send_from_directory, Blueprint

app = Flask(__name__)
files_bp = Blueprint("files", __name__)

# Configs:
_DEFAULT_PAGE_SIZE = 1000
_FILE_LIMIT = 50000
_FILE_NAME_TO_PROPORTION = {
    "150_kb.pdf": 0.2,  # 20%
    "500_kb.pdf": 0.2,  # 20%
    "1_mb.pdf": 0.2,  # 20%
    "5_mb.pdf": 0.2, # 20%
    "10_mb.pdf": 0.15, # 15%
    "100_mb.pdf": 0.05 # 5%
}
_NEXT_URL_FORMAT = "{base}v1/files?$skip={offset}&$top={page_size}&$filter={filter}"
_SET_TO_CURRENT_TIME = False

# Function to return error messages for http errors
def create_error_response(http_code: int, code: str, message: str) -> Response:
    return make_response(jsonify({"code": code, "message": message}), http_code)

# Hardcoded auth values - Replace with correct credentials:
# _JWT_TOKEN = "some_jwt_token"
# _CLIENT_ID = "some_client_id"
# _CLIENT_SECRET = "some_client_secret"

# This gateway doesn't use auth, but setup auth validation if needed
# @files_bp.before_request
# def validate_auth():
#     authorization = request.headers.get("Authorization")
#     if not authorization:
#         return create_error_response(
#             401, "AUTHENTICATION_FAILED", "Authorization header missing."
#         )

#     token = authorization.replace("Bearer ", "")
#     if not token:
#         return create_error_response(
#             401, "AUTHENTICATION_FAILED", "Bearer token missing."
#         )

#     if token != _JWT_TOKEN:
#         return create_error_response(
#             401, "AUTHENTICATION_FAILED", "Bearer token invalid."
#         )

# Starter code for sample oauth authentication if needed
# @app.route("/oauth2/token", methods=["POST"])
# def token():
#     content_type = request.headers.get("Content-Type")
#     if not content_type or content_type != "application/x-www-form-urlencoded":
#         return create_error_response(
#             415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type header missing or invalid."
#         )

#     grant_type = request.form.get("grant_type")
#     if not grant_type or grant_type != "client_credentials":
#         return create_error_response(400, "INVALID_REQUEST", "Invalid grant type.")

#     authorization_header = request.headers.get("Authorization")
#     if not authorization_header:
#         return create_error_response(
#             401, "INVALID_REQUEST", "Authorization header missing."
#         )

#     encoded_credentials = authorization_header.replace("Basic ", "")
#     if not verify_basic_auth(encoded_credentials):
#         return create_error_response(
#             401, "INVALID_CLIENT", "Invalid client ID or secret."
#         )

#     return make_response(
#         jsonify(
#             {
#                 "access_token": _JWT_TOKEN,
#                 "token_type": "Bearer",
#                 "expires_in": 3600,
#             }
#         ),
#         200,
#     )

# Starter code for sample basic authentication if needed
# def verify_basic_auth(encoded_credentials: str) -> bool:
#     try:
#         encoded_credentials = encoded_credentials.strip()
#         decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")
#         username, password = decoded_credentials.split(":", 1)
#         return username == _CLIENT_ID and password == _CLIENT_SECRET
#     except Exception as e:
#         return False

# Handle incoming GET files requests
@files_bp.route("/files", methods=["GET"])
def get_files() -> Response:
    page_size = request.args.get(key="$top", default=_DEFAULT_PAGE_SIZE, type=int)
    offset = request.args.get(key="$skip", default=0, type=int)
    filter = request.args.get(key="$filter", default="", type=str)

    files, next_url = list_files(offset, page_size, filter)

    return make_response(jsonify({"value": files, "@odata.nextLink": next_url, "@odata.context": request.url}), 200)

def list_files(offset: int, page_size: int, filter: str) -> Tuple[List[Dict], str]:
    # Calculate distribution within the given page_size
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
            files_to_return.append(
                {
                    "id": file_id, # required field, must be unique
                    "name": file_name_with_index, # required field
                    "status": "active",
                    "last_modified_datetime": (
                        "2023-04-17T12:34:56Z"
                        if not _SET_TO_CURRENT_TIME
                        else current_time
                    ),
                    "created_datetime": (
                        "2023-01-01T00:00:00Z"
                        if not _SET_TO_CURRENT_TIME
                        else current_time
                    ),
                    "content": {
                        "download_path": f"{file_id}/download",
                        "mime_type": "application/pdf" if file_name.endswith(".pdf") else "text/plain", # required field
                    },
                    "external_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf" # required field
                }
            )
            current_index += 1

    # Calculate the new offset
    new_offset = offset + page_size if offset + page_size < _FILE_LIMIT else _FILE_LIMIT

    # Generate the next URL if new_offset < 1000
    next_url = (
        _NEXT_URL_FORMAT.format(
            base=request.url_root, offset=new_offset, page_size=page_size, filter=filter
        )
        if new_offset < _FILE_LIMIT
        else ""
    )

    return files_to_return, next_url


@files_bp.route("/files/<file_id>", methods=["GET"])
def get_file_metadata(file_id: str):
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    file_name_with_index = f"{file_id}"
    file_id = base64.b64encode(file_name_with_index.encode()).decode()
    file_metadata = {
                    "id": file_id, # required field, must be unique
                    "name": file_name_with_index, # required field
                    "status": "active",
                    "last_modified_datetime": (
                        "2023-04-17T12:34:56Z"
                        if not _SET_TO_CURRENT_TIME
                        else current_time
                    ),
                    "created_datetime": (
                        "2023-01-01T00:00:00Z"
                        if not _SET_TO_CURRENT_TIME
                        else current_time
                    ),
                    "content": {
                        "download_path": f"{file_id}/download",
                        "mime_type": "application/pdf" # required field
                    },
                    "external_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf" # required field
            }

    return make_response(jsonify({"value": file_metadata, "@odata.context": request.url}), 200)

@files_bp.route("/files/<file_id>/download", methods=["GET"])
def download_file(file_id: str):
    # Define the directory where your files are stored
    # This path should be absolute or relative to the root of your application
    directory_path = './sample-content'
    filename = f"{file_id}.pdf"

    # Ensure the file exists and handle 404 errors
    if not os.path.isfile(os.path.join(directory_path, filename)):
        return create_error_response(404, "FILE_NOT_FOUND", str(e))
    
    # Send the file with 'application/octet-stream' content type
    return send_from_directory(directory_path, filename, as_attachment=True, mimetype='application/octet-stream')

app.register_blueprint(files_bp, url_prefix="/v1")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)