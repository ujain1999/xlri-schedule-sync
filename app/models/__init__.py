"""Importing any submodule of app.models runs this file first (Python always
executes a package's __init__.py before a submodule within it), so importing
all model classes here guarantees SQLAlchemy's metadata/mapper registry is
fully populated -- regardless of which specific model a caller imported
directly. Without this, code paths that don't go through app.main's full
router import chain (standalone scripts, future CLI tools, etc.) can hit
NoReferencedTableError when SQLAlchemy tries to resolve a foreign key to a
table that was never registered.
"""

from app.models.base import Base  # noqa: F401
from app.models.event_mapping import EventMapping, SourceType  # noqa: F401
from app.models.google_oauth import GoogleOAuthToken  # noqa: F401
from app.models.session import Session  # noqa: F401
from app.models.sync_run import ErrorStage, SyncRun, SyncStatus  # noqa: F401
from app.models.sync_settings import SyncSettings  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.xlri_credentials import XlriCredentials  # noqa: F401
