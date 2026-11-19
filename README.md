# tiny_cuckoo_filter

A small Cuckoo Filter that supports membership tests and deletion.

```python
from tiny_cuckoo_filter import CuckooFilter, CuckooFilterError

filt = CuckooFilter(capacity=1024, seed=0)
filt.insert("alice")
filt.insert(b"raw-bytes")

assert "alice" in filt
assert filt.contains(b"raw-bytes")
assert "bob" not in filt

assert filt.delete("alice") is True
assert filt.delete("alice") is False  # already gone
assert len(filt) == 1
```

## Why this exists

A plain set answers membership, but it stores every item in full.  A Bloom
filter is compact but cannot delete.  A Cuckoo Filter stores a short
fingerprint per item in a table of buckets, so it is compact *and* it can
remove items, at the cost of a small false-positive rate.  This library makes
the trade-off explicit: fingerprints are 16 bits, so the per-bucket false
positive probability is about 2**-16, and the table is sized for a load factor
of at most 0.5 at the requested capacity.

Two decisions are worth calling out because they are visible in the API:

* Hashing uses `hashlib.blake2b` rather than the built-in `hash`, so results
  are stable across processes and Python versions.  That makes the filter
  reproducible and keeps the tests deterministic.
* `insert` raises `CuckooFilterError` when the table cannot make room, instead
  of returning `False`.  Silent failure is easy to miss; an exception forces
the caller to decide what to do.

## The awkward edge

Duplicates are allowed, and the filter counts *fingerprints*, not distinct
items.  Inserting `"alice"` twice makes `len(filt) == 2`, and each `delete`
removes exactly one fingerprint.  This is what makes deletion well defined:
the filter never has to guess which occurrence you meant.

A second edge: because only fingerprints are stored, `contains` can return
`True` for an item that was never inserted.  The false-positive rate is small
but non-zero, and it grows as the table fills.  If you need exact membership,
use a set.

## API

* `CuckooFilter(capacity=1024, bucket_size=4, max_kicks=500, seed=None)` —
  construct a filter.  `capacity` is rounded up to a power of two.  Passing a
  fixed `seed` makes relocation deterministic.
* `filt.insert(item)` — insert `item`.  Raises `CuckooFilterError` if the
  table is too full.
* `filt.contains(item)` — return `True` if `item` may be present.
* `item in filt` — same as `contains`.
* `filt.delete(item)` — remove one fingerprint for `item`; returns `True` if
  one was removed.
* `filt.clear()` — remove every fingerprint.
* `filt.extend(items)` — insert every item from an iterable.
* `len(filt)` — number of stored fingerprints.
* `filt.capacity` — number of buckets (a power of two).
* `filt.bucket_size` — fingerprints per bucket.
* `iter(filt)` — yield the raw fingerprints currently stored.

Items may be `bytes`, `str`, or any object with a stable `repr`; the repr is
encoded as UTF-8 before hashing.
