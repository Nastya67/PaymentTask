"""Authentication.

Authentication is out of scope: Replacing that with a real token only changes
load_user_from_request.
"""

import uuid
from dataclasses import dataclass
from http import HTTPStatus

from flask import Request
from flask_login import LoginManager, UserMixin

login_manager = LoginManager()
login_manager.session_protection = None


@dataclass(frozen=True)
class CurrentUser(UserMixin):
    """
    Represents current user.

    Could be replaced with a User object.
    """
    id: uuid.UUID


@login_manager.request_loader
def load_user_from_request(request: Request) -> CurrentUser | None:
    try:
        return CurrentUser(uuid.UUID(request.headers["X-User-Id"]))
    except (KeyError, ValueError):
        return None


@login_manager.unauthorized_handler
def unauthorized():
    return {"error": "Missing or invalid X-User-Id header"}, HTTPStatus.UNAUTHORIZED
