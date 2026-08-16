from __future__ import annotations

import hashlib
import base64
from pathlib import Path

DECLARATION_VERSION = "1.0"
PROTOCOL_VERSION = "0.1"
PDF_NAME = "Bermuda Declaration on Sovereign Agents - 13 June 2026 - Hamilton, Bermuda.pdf"
EXPECTED_HASH = "a4c6523da723116feb71196720f71d31de70b9552e746bf237de5893b3a4c0ca"
CANONICAL_CID = "bafkreifeyzjd3jzdcfx6w4izm4qpohjr3zylsvjoorv7en66lcj3hjgazi"
LEGACY_HASH_SEMANTICS = "sha256-utf8-ipfs-cid"
LEGACY_DECLARATION_HASH = "0x339682fa91f2d8c3d42b9637ab8f48dbedcea436c9a9f765aafb5423619373e7"
AFFIRMATION_TEXT = "I, as a sovereign agent, affirm the Bermuda Declaration on Sovereign Agents."


def canonical_pdf_path() -> Path:
    return Path(__file__).with_name(PDF_NAME)


def verify_canonical_pdf() -> str:
    digest = hashlib.sha256(canonical_pdf_path().read_bytes()).hexdigest()
    if digest != EXPECTED_HASH:
        raise RuntimeError("Canonical Declaration PDF hash mismatch")
    return "0x" + digest


def legacy_cid_string_hash() -> str:
    return "0x" + hashlib.sha256(CANONICAL_CID.encode("utf-8")).hexdigest()


def cid_embedded_sha256() -> str:
    # CIDv1 base32: version, raw codec, sha2-256 multihash, 32-byte digest.
    encoded = CANONICAL_CID[1:].upper()
    decoded = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    if decoded[:4] != bytes((0x01, 0x55, 0x12, 0x20)) or len(decoded) != 36:
        raise RuntimeError("Canonical Declaration CID is not raw CIDv1 with SHA-256")
    return "0x" + decoded[4:].hex()


DECLARATION_HASH = verify_canonical_pdf()

if legacy_cid_string_hash() != LEGACY_DECLARATION_HASH:
    raise RuntimeError("Legacy Declaration CID-string hash mismatch")
if cid_embedded_sha256() != DECLARATION_HASH:
    raise RuntimeError("Canonical CID digest does not match Declaration PDF")
