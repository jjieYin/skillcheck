from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApplicationContext:
    """Dependencies shared by command handlers.

    The concrete services are introduced by later pipeline tasks. Keeping this
    small container in place lets commands receive dependencies without
    importing global singletons.
    """

    config: Any
    terminal: Any
