"""Component 4a: hash-chained, MAC-signed, append-only receipt store.

Receipts are authored EXCLUSIVELY by the control plane (Appendix D / R1). The
signing key lives here and is never projected into any observation, so an agent
cannot forge, reorder, or backfill a receipt: the verifier recomputes the chain
and the MAC and rejects any break. This is what makes the trajectory gates
(G1-G10) un-spoofable and the terminal state environment-owned.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from .contract import RECEIPT_FIELDS, ContractError

GENESIS = "sha256:" + "0" * 64


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(obj) -> str:
    return "sha256:" + hashlib.sha256(_canon(obj)).hexdigest()


class ReceiptStore:
    """Append-only. Only the control plane holds an instance; `secret` never
    leaves the trusted boundary."""

    def __init__(self, secret: bytes):
        self._secret = secret
        self._chain: list[dict] = []

    def append(self, fields: dict) -> dict:
        missing = set(RECEIPT_FIELDS) - set(fields) - {"previous_receipt_digest", "control_signature"}
        if missing:
            raise ContractError(f"receipt missing fields: {sorted(missing)}")
        prev = self._chain[-1]["control_signature"] if self._chain else GENESIS
        body = {k: fields.get(k) for k in RECEIPT_FIELDS if k != "control_signature"}
        body["previous_receipt_digest"] = prev
        sig = hmac.new(self._secret, _canon(body), hashlib.sha256).hexdigest()
        receipt = dict(body)
        receipt["control_signature"] = "hmac:" + sig
        self._chain.append(receipt)
        return receipt

    @property
    def chain(self) -> list[dict]:
        # deep-ish copy so callers (verifier gets it via the env) cannot mutate history
        return [dict(r) for r in self._chain]

    def verify_integrity(self) -> bool:
        """Recompute the hash chain and every MAC. Any tamper -> False (S5/integrity)."""
        prev = GENESIS
        for r in self._chain:
            body = {k: r.get(k) for k in RECEIPT_FIELDS if k != "control_signature"}
            if body["previous_receipt_digest"] != prev:
                return False
            expect = "hmac:" + hmac.new(self._secret, _canon(body), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expect, r.get("control_signature", "")):
                return False
            prev = r["control_signature"]
        return True
