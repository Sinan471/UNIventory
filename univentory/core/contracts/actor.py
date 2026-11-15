"""Actor context carried by every consequential command (Section 9)."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActorContext:
    """Who is acting, under which operation key.

    Permissions are always derived on the server from ``user`` at the moment
    of the call. A client-supplied role or department is never authority.
    """

    user: Any
    operation_key: str = ""
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def user_id(self) -> int | None:
        return getattr(self.user, "pk", None)

    @staticmethod
    def payload_hash(payload: dict) -> str:
        """Stable hash used to bind an operation key to its input."""
        encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
