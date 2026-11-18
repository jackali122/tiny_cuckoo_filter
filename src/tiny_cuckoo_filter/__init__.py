"""Public surface of tiny_cuckoo_filter.

Only :class:`CuckooFilter` and :class:`CuckooFilterError` are exported; the
bucket internals live in :mod:`tiny_cuckoo_filter.core` so that the public
namespace stays small and stable.
"""

from .core import CuckooFilter, CuckooFilterError

__all__ = ["CuckooFilter", "CuckooFilterError"]
