import re
from datetime import datetime, timedelta

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)
from flask import Flask, jsonify, make_response, request

app = Flask(__name__)

FORM_1 = {
    "id": "123456789",  # Stable identifier of the form. Should not change.
    "domain": "IT",  # Specifies the domain the form belongs to.
    "title": "Request ERP System Access",  # Title of the form. End-user facing.
    "short_description": "Lorem",  # Form description consumed in search
    "description": "Lorem ipsum",  # Form description consumed in search
    "image_url": "https://form-image.example.com/stock-image.png",
    "url": "https://google.com/forms?id=23493",  # Self-service portal URL to complete the form
    "last_updated_at": "2021-10-20T17:28:52Z",  # When the form was last updated
    "fields": [
        {
            # The label for this input field
            "label": "Who is this account for?",
            # The name of the field provided during submission as key in key-value pairs
            "name": "requested_for",
            # Placeholder text that will appear when the form is rendered.
            "placeholder": "Select a user",
            # Additional help text that will appear as a tooltip or help text near the form field.
            "help": "The user who needs to be given ERP system access",
            # Type = one of the above defined field types.
            "type": "SINGLE_USER_OPTION_PICKER",
            # Specifies if the field is mandatory during form submission.
            "required": True,
            # Specifies if the field is visible initially on form render.
            "visible": True,
            "options": [],
        },
        {
            "label": "What permissions do you need?",
            "name": "permissions",
            "placeholder": None,
            "help": 'You can check <a href="help.moveworks.com/erp">this link</a> for help.',
            "type": "MULTI_OPTION_PICKER",
            "required": True,
            "visible": True,
            "options": [
                {
                    # options.label = End user facing option in the dropdown
                    "label": "Banking Manager",
                    # options.label = The backend value associated with this selection. Used as value in key-value pair during form submission.
                    "value": "banking_manager",
                },
                {"label": "Returns Preparer", "value": "returns_preparer"},
            ],
        },
        {
            "label": "Do you need read or write access?",
            "name": "read_or_write",
            "placeholder": None,
            "help": None,
            "type": "SINGLE_OPTION_PICKER",
            "required": True,
            "visible": True,
            "options": [
                {"label": "Read", "value": "read"},
                {"label": "Write", "value": "write"},
            ],
        },
        {
            "label": "Why do you need this access?",
            "name": "business_justification",
            "placeholder": None,
            "help": None,
            "type": "SINGLE_LINE_TEXT",
            "required": False,
            "visible": True,
            "options": [],
        },
        {
            "label": "When do you need this to take effect?",
            "name": "effective_date",
            "placeholder": None,
            "help": None,
            "type": "DATE_PICKER",
            "required": False,
            "visible": True,
            "options": [],
        },
        {
            "label": "2FA is recommended for ERP access.",
            "name": "2fa_device_advice",
            # This has no effect on a label.
            "placeholder": None,
            # This has no effect on a label.
            "help": None,
            "type": "LABEL",
            # This has no effect on a label.
            "required": False,
            "visible": False,
            "options": [],
        },
        {
            "label": "Do you want to also give them a 2FA device?",
            "name": "2fa_device",
            # This has no effect on a checkbox.
            "placeholder": None,
            "help": None,
            "type": "CHECKBOX",
            # This has no effect on a checkbox.
            "required": False,
            "visible": False,
            "options": [],
        },
        {
            "label": "Any additional details?",
            "name": "additional_details",
            "placeholder": None,
            "help": None,
            "type": "MULTI_LINE_TEXT",
            "required": False,
            "visible": True,
            "options": [],
        },
    ],
    # Configuration to show a mandatory business justification if "write" access is needed.
    "dynamic_field_rules": [
        {
            "name": "read_or_write_ctrl_business_justification",
            # This field has no effect when there is one condition only
            "logical": "OR",
            "conditions": [
                {
                    # Field to check
                    "field_name": "read_or_write",
                    "operator": "EQUALS",
                    "value": "read",
                }
            ],
            # Apply the following actions when the above condition is True.
            # Inverts if the condition is False
            "actions": [
                {
                    # Field to alter
                    "field_name": "business_justification",
                    # Set field visible
                    "visible": True,
                    # Set field required
                    "required": True,
                }
            ],
        },
        {
            "name": "read_or_write_ctrl_additional_details",
            "logical": "AND",
            "conditions": [
                {"field_name": "read_or_write", "operator": "NOT_EMPTY", "value": None}
            ],
            "actions": [
                {"field_name": "additional_details", "visible": True, "required": True}
            ],
        },
        {
            "name": "make_2fa_visible",
            "logical": "AND",
            "conditions": [
                {
                    "field_name": "read_or_write",
                    # NOT_EMPTY would have worked too
                    "operator": "IN",
                    "value": ["read", "write"],
                },
                {
                    "field_name": "permissions",
                    "operator": "EQUALS",
                    "value": "banking_manager",
                },
            ],
            "actions": [
                {"field_name": "2fa_device_advice", "visible": True, "required": False},
                {"field_name": "2fa_device", "visible": True, "required": False},
            ],
        },
    ],
}


def handle_form_1_submit(json_contents):
    print(json_contents)


FORM_LIB = {FORM_1["id"]: {"form": FORM_1, "handler": handle_form_1_submit}}
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
********************* Get a public key following our Gateway Authentication https://developer.moveworks.com/gateway/authentication/ *********************
-----END PUBLIC KEY-----
"""


def make_error(http_code: str, code: str, message: str) -> dict:
    return make_response({"error": {"code": code, "message": message}}, http_code)


def validate_auth() -> str:
    try:
        token = request.headers["Authorization"].replace("Bearer ", "")
        jwt_header = jwt.get_unverified_header(token)
    except:
        return "Bearer token missing."

    try:
        jwt.decode(
            token,
            PUBLIC_KEY,
            algorithms=[
                jwt_header["alg"],
            ],
            options={"verify_signature": True},
            audience="https://moveworks-gateway.customer.com",
            issuer="moveworks",
            verify=True,
        )
    except Exception as e:
        return "JWT Verification Failed: " + str(e)


@app.route("/forms")
def list_forms():
    err_msg = validate_auth()
    if err_msg:
        return make_error(401, "AUTHENTICATION_FAILED", err_msg)
    return jsonify({"results": list(map(lambda x: x["form"], FORM_LIB.values()))})


@app.route("/forms/<form_id>")
def get_form(form_id: str):
    err_msg = validate_auth()
    if err_msg:
        return make_error(401, "AUTHENTICATION_FAILED", err_msg)

    try:
        return FORM_LIB[form_id]["form"]
    except KeyError:
        return make_error(404, "NOT_FOUND", f"Form ID {form_id} does not exist.")


@app.route("/forms/<form_id>/submit", methods=["POST"])
def submit_form(form_id: str):
    err_msg = validate_auth()
    if err_msg:
        return make_error(401, "AUTHENTICATION_FAILED", err_msg)

    try:
        handler = FORM_LIB[form_id]["handler"]
        handler(request.json)
        return make_response(jsonify({"ticket_id": None}), 200)
    except KeyError:
        return make_error(404, "NOT_FOUND", f"Form ID {form_id} does not exist.")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
