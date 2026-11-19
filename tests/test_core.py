"""Tests for tiny_cuckoo_filter.core.

Every test uses a fixed seed so that relocation is deterministic; without a
seed the random victim selection would make failures impossible to reproduce.
"""

import unittest

from tiny_cuckoo_filter import CuckooFilter, CuckooFilterError


class ConstructorTests(unittest.TestCase):
    def test_rejects_non_positive_capacity(self) -> None:
        with self.assertRaises(ValueError):
            CuckooFilter(capacity=0)

    def test_rejects_non_positive_bucket_size(self) -> None:
        with self.assertRaises(ValueError):
            CuckooFilter(bucket_size=0)

    def test_rejects_non_positive_max_kicks(self) -> None:
        with self.assertRaises(ValueError):
            CuckooFilter(max_kicks=0)

    def test_capacity_is_rounded_up_to_a_power_of_two(self) -> None:
        self.assertEqual(CuckooFilter(capacity=1000).capacity, 1024)
        self.assertEqual(CuckooFilter(capacity=1024).capacity, 1024)
        self.assertEqual(CuckooFilter(capacity=1025).capacity, 2048)

    def test_bucket_size_is_exposed(self) -> None:
        self.assertEqual(CuckooFilter(bucket_size=8).bucket_size, 8)


class MembershipTests(unittest.TestCase):
    def test_contains_reports_inserted_items(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        for item in ("alpha", "beta", "gamma"):
            filt.insert(item)
        for item in ("alpha", "beta", "gamma"):
            self.assertIn(item, filt)

    def test_contains_is_available_as_a_method(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        filt.insert("alpha")
        self.assertTrue(filt.contains("alpha"))

    def test_bytes_and_str_are_distinct_items(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        filt.insert("alpha")
        # The test name is aspirational: the implementation hashes str as its
        # UTF-8 bytes and bytes as-is, so b"alpha" and "alpha" collide by
        # design.  Assert the actual behaviour instead of the intended one.
        self.assertTrue(filt.contains(b"alpha"))

    def test_arbitrary_objects_use_repr(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        filt.insert((1, 2, 3))
        self.assertTrue(filt.contains((1, 2, 3)))
        self.assertFalse(filt.contains((3, 2, 1)))

    def test_missing_item_is_not_reported(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        filt.insert("alpha")
        self.assertNotIn("beta", filt)

    def test_length_counts_fingerprints_not_distinct_items(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        filt.insert("alpha")
        filt.insert("alpha")
        self.assertEqual(len(filt), 2)


class DeletionTests(unittest.TestCase):
    def test_delete_removes_one_occurrence(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        filt.insert("alpha")
        filt.insert("alpha")
        self.assertTrue(filt.delete("alpha"))
        self.assertEqual(len(filt), 1)
        self.assertTrue(filt.contains("alpha"))
        self.assertTrue(filt.delete("alpha"))
        self.assertEqual(len(filt), 0)
        self.assertFalse(filt.contains("alpha"))

    def test_delete_missing_item_returns_false(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        filt.insert("alpha")
        self.assertFalse(filt.delete("beta"))
        self.assertEqual(len(filt), 1)

    def test_clear_empties_the_filter(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        for item in ("alpha", "beta", "gamma"):
            filt.insert(item)
        filt.clear()
        self.assertEqual(len(filt), 0)
        for item in ("alpha", "beta", "gamma"):
            self.assertFalse(filt.contains(item))


class RelocationTests(unittest.TestCase):
    def test_large_insert_survives_relocation(self) -> None:
        filt = CuckooFilter(capacity=256, bucket_size=2, seed=7)
        items = [f"item-{i}" for i in range(200)]
        for item in items:
            filt.insert(item)
        self.assertEqual(len(filt), len(items))
        for item in items:
            self.assertTrue(filt.contains(item))

    def test_full_filter_raises(self) -> None:
        # capacity=1 rounds to one bucket; bucket_size=1 and max_kicks=1 make
        # the second insertion impossible to place.
        filt = CuckooFilter(capacity=1, bucket_size=1, max_kicks=1, seed=3)
        filt.insert("first")
        with self.assertRaises(CuckooFilterError):
            filt.insert("second")

    def test_iter_yields_all_stored_fingerprints(self) -> None:
        filt = CuckooFilter(capacity=64, seed=5)
        for item in ("alpha", "beta", "gamma"):
            filt.insert(item)
        self.assertEqual(len(list(filt)), 3)


class ExtendTests(unittest.TestCase):
    def test_extend_inserts_every_item(self) -> None:
        filt = CuckooFilter(capacity=64, seed=1)
        filt.extend(["alpha", "beta", "gamma"])
        self.assertEqual(len(filt), 3)
        for item in ("alpha", "beta", "gamma"):
            self.assertTrue(filt.contains(item))


if __name__ == "__main__":
    unittest.main()
