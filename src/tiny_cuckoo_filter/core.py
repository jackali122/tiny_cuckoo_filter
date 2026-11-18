"""A small Cuckoo Filter with dynamic deletion.

A Cuckoo Filter stores short fingerprints of inserted items in a table of
buckets.  Each item has two candidate buckets derived from its fingerprint,
and insertion relocates existing fingerprints (cuckoo hashing) when both
candidate buckets are full.  Deletion removes a fingerprint from one of its
candidate buckets.

Design choices worth stating up front:

* Items are hashed to a 64-bit value with :func:`hashlib.blake2b` rather than
the built-in :func:`hash`, because the built-in hash is salted per process and
would make the filter non-reproducible across runs.  Reproducibility matters
for tests and for any persisted table.
* Fingerprints are 16 bits, so the false-positive rate is roughly 2**-16 per
candidate bucket.  A larger fingerprint would lower that rate at the cost of
more collisions between distinct items, which is the usual trade-off.
* ``insert`` raises :class:`CuckooFilterError` instead of returning ``False``
  when the table cannot make room.  Silent failure is the kind of bug that
  shows up much later, so the caller is forced to handle it.
"""

from __future__ import annotations

import hashlib
import random
from typing import Iterable, Iterator, Optional

__all__ = ["CuckooFilter", "CuckooFilterError"]


class CuckooFilterError(Exception):
    """Raised when the filter cannot accept another item."""


# 16-bit fingerprints keep the false-positive probability near 2**-16 while
# leaving room for many distinct fingerprints in a small table.
_FINGERPRINT_BITS = 16
_FINGERPRINT_MASK = (1 << _FINGERPRINT_BITS) - 1

# A fingerprint of zero is reserved: it lets ``_fingerprint`` map a raw hash of
# zero to a non-zero value without a second hash call.
_ZERO_FINGERPRINT = 0


def _hash_bytes(data: bytes) -> int:
    """Return a stable 64-bit hash of *data*.

    blake2b is used instead of :func:`hash` so that results are identical
    across processes and Python versions.
    """

    digest = hashlib.blake2b(data, digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _to_bytes(item: object) -> bytes:
    """Convert *item* to bytes for hashing.

    ``bytes`` and ``str`` are handled directly; everything else falls back to
    ``repr``.  The fallback is deliberately explicit: silently hashing the
    ``id`` of an object would make the filter non-deterministic.
    """

    if isinstance(item, bytes):
        return item
    if isinstance(item, str):
        return item.encode("utf-8")
    return repr(item).encode("utf-8")


class CuckooFilter:
    """A probabilistic set with deletion.

    Parameters
    ----------
    capacity:
        Expected number of items.  The table is sized so that a load factor of
        at most 0.5 is reached at this capacity, which keeps relocation cheap.
    bucket_size:
        Number of fingerprints per bucket.  Larger buckets reduce relocation
        pressure but cost more time on lookup.
    max_kicks:
        Maximum number of relocations attempted before insertion fails.
    seed:
        Seed for the internal :class:`random.Random`.  Passing a fixed seed
        makes relocation deterministic, which the tests rely on.
    """

    def __init__(
        self,
        capacity: int = 1024,
        bucket_size: int = 4,
        max_kicks: int = 500,
        seed: Optional[int] = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if bucket_size <= 0:
            raise ValueError("bucket_size must be positive")
        if max_kicks <= 0:
            raise ValueError("max_kicks must be positive")

        self._bucket_size = bucket_size
        self._max_kicks = max_kicks
        # Round up to a power of two so that the alternate-bucket formula can
        # use a bitmask instead of a modulo operation.
        self._num_buckets = self._next_power_of_two(max(1, capacity))
        self._buckets: list[list[int]] = [
            [] for _ in range(self._num_buckets)
        ]
        self._size = 0
        self._rng = random.Random(seed)

    # -- introspection -------------------------------------------------

    def __len__(self) -> int:
        """Return the number of stored fingerprints.

        This counts fingerprints, not distinct items: a duplicate insert adds
        another fingerprint.
        """

        return self._size

    def __contains__(self, item: object) -> bool:
        return self.contains(item)

    def __iter__(self) -> Iterator[int]:
        """Yield the raw fingerprints currently stored.

        The order is bucket order.  This is mainly useful for debugging and
        for tests that need to observe relocation.
        """

        for bucket in self._buckets:
            yield from bucket

    @property
    def capacity(self) -> int:
        """Return the number of buckets in the table."""

        return self._num_buckets

    @property
    def bucket_size(self) -> int:
        """Return the number of fingerprints each bucket can hold."""

        return self._bucket_size

    # -- public operations ---------------------------------------------

    def insert(self, item: object) -> None:
        """Insert *item*.

        Duplicates are allowed and each insert stores a separate fingerprint.
        Raises :class:`CuckooFilterError` if the table is too full to make
        room after ``max_kicks`` relocations.
        """

        fingerprint = self._fingerprint(item)
        index = self._primary_index(item)
        self._insert_fingerprint(fingerprint, index)

    def contains(self, item: object) -> bool:
        """Return ``True`` if *item* may be present.

        False positives are possible; false negatives are not, provided the
        item was inserted and never deleted.
        """

        fingerprint = self._fingerprint(item)
        index = self._primary_index(item)
        return self._find(fingerprint, index) is not None

    def delete(self, item: object) -> bool:
        """Remove one fingerprint for *item*.

        Returns ``True`` if a fingerprint was removed and ``False`` if the
        item was not present.  When the same item was inserted more than once,
        only one fingerprint is removed per call.
        """

        fingerprint = self._fingerprint(item)
        index = self._primary_index(item)
        located = self._find(fingerprint, index)
        if located is None:
            return False
        bucket_index, offset = located
        del self._buckets[bucket_index][offset]
        self._size -= 1
        return True

    def clear(self) -> None:
        """Remove every fingerprint."""

        for bucket in self._buckets:
            bucket.clear()
        self._size = 0

    def extend(self, items: Iterable[object]) -> None:
        """Insert every item from *items*.

        This is a convenience wrapper; it does not preallocate, so a large
        iterable can still exhaust the table.
        """

        for item in items:
            self.insert(item)

    # -- internals -----------------------------------------------------

    @staticmethod
    def _next_power_of_two(value: int) -> int:
        power = 1
        while power < value:
            power <<= 1
        return power

    def _fingerprint(self, item: object) -> int:
        """Return a non-zero 16-bit fingerprint for *item*."""

        raw = _hash_bytes(_to_bytes(item)) & _FINGERPRINT_MASK
        # Map zero to one so that the reserved zero value is never stored.
        return raw or 1

    def _primary_index(self, item: object) -> int:
        """Return the primary bucket index for *item*."""

        return _hash_bytes(_to_bytes(item)) % self._num_buckets

    def _alternate_index(self, fingerprint: int, index: int) -> int:
        """Return the alternate bucket index for *fingerprint* at *index*.

        XOR with a hash of the fingerprint keeps the two candidate buckets
        independent of the item's raw hash while remaining cheap to compute
        from the fingerprint alone, which is all a relocated entry carries.
        """

        return (index ^ (_hash_bytes(fingerprint.to_bytes(2, "big")) % self._num_buckets))

    def _candidate_indices(self, fingerprint: int, index: int) -> tuple[int, int]:
        alternate = self._alternate_index(fingerprint, index)
        return index, alternate

    def _find(self, fingerprint: int, index: int) -> Optional[tuple[int, int]]:
        """Locate *fingerprint* in either candidate bucket.

        Returns ``(bucket_index, offset)`` or ``None``.
        """

        for candidate in self._candidate_indices(fingerprint, index):
            bucket = self._buckets[candidate]
            for offset, stored in enumerate(bucket):
                if stored == fingerprint:
                    return candidate, offset
        return None

    def _insert_fingerprint(self, fingerprint: int, index: int) -> None:
        """Insert *fingerprint* starting from bucket *index*."""

        if self._try_put(fingerprint, index):
            self._size += 1
            return

        # Both candidate buckets are full; relocate existing fingerprints.
        current_fingerprint = fingerprint
        current_index = index
        for _ in range(self._max_kicks):
            bucket = self._buckets[current_index]
            victim_offset = self._rng.randrange(len(bucket))
            bucket[victim_offset], current_fingerprint = (
                current_fingerprint,
                bucket[victim_offset],
            )
            current_index = self._alternate_index(current_fingerprint, current_index)
            if self._try_put(current_fingerprint, current_index):
                self._size += 1
                return

        raise CuckooFilterError(
            "filter is full: could not place fingerprint after "
            f"{self._max_kicks} relocations"
        )

    def _try_put(self, fingerprint: int, index: int) -> bool:
        """Try to append *fingerprint* to one of its candidate buckets."""

        for candidate in self._candidate_indices(fingerprint, index):
            bucket = self._buckets[candidate]
            if len(bucket) < self._bucket_size:
                bucket.append(fingerprint)
                return True
        return False
