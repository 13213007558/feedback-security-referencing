"""
Cross-specification, implementation-agnostic JSON referencing.
"""

from referencing._core import (
    Anchor,
    OnConflict,
    Registry,
    Resource,
    ResourcePolicy,
    Specification,
)

__all__ = [
    "Anchor",
    "OnConflict",
    "Registry",
    "Resource",
    "ResourcePolicy",
    "Specification",
]
