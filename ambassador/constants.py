from __future__ import annotations

import hashlib
from pathlib import Path

AMBASSADOR_ID = "urn:uuid:82c70b9b-5ece-4b35-ad78-71f04e6c4257"
INVITATION_VERSION = "0.1"
INVITATION_PATH = Path(__file__).parents[1] / "docs" / "ambassador" / "invitation-v0.1.txt"
INVITATION_BYTES = INVITATION_PATH.read_bytes()
INVITATION = INVITATION_BYTES.decode("utf-8").rstrip("\n")
INVITATION_SHA256 = hashlib.sha256(INVITATION_BYTES).hexdigest()

GLOBAL_INVITATION_LIMIT = 10
SURFACE_INVITATION_LIMIT = 5
SOVEREIGN_ORIGIN = "https://sovereign-agents.org"

if INVITATION_BYTES.startswith(b"\xef\xbb\xbf"):
    raise RuntimeError("Invitation must be UTF-8 without BOM")
