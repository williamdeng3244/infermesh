# SPDX-License-Identifier: Apache-2.0
"""Tiered KV cache (M17): hot LRU in RAM, cold offload to SSD, restore on hit."""

from infermesh.backends.transformers.kv_cache import TieredKVCache, prefix_key


def test_prefix_key_stable_and_distinct():
    assert prefix_key([1, 2, 3]) == prefix_key([1, 2, 3])
    assert prefix_key([1, 2, 3]) != prefix_key([1, 2, 4])


def test_hot_lru_and_cold_offload(tmp_path):
    c = TieredKVCache(hot_capacity=2, cold_dir=str(tmp_path))
    for i in range(5):
        c.put(f"k{i}", {"v": i})
    s = c.stats()
    assert s["hot"] == 2 and s["cold"] == 3                  # 2 hot, 3 spilled to SSD
    assert len(list(tmp_path.glob("*.kv"))) == 3
    assert c.get("k0") == {"v": 0}                           # restored from SSD
    assert c.stats()["hot"] <= 2                             # restore respects the hot cap
    assert c.get("missing") is None


def test_survives_new_instance(tmp_path):
    c = TieredKVCache(hot_capacity=1, cold_dir=str(tmp_path))
    c.put("a", [1, 2, 3])
    c.put("b", [4, 5, 6])                                    # 'a' spills to cold
    c2 = TieredKVCache(hot_capacity=1, cold_dir=str(tmp_path))   # fresh instance, same dir
    assert c2.get("a") == [1, 2, 3]                          # survives a "restart"


def test_no_cold_dir_is_ram_only():
    c = TieredKVCache(hot_capacity=1)                        # no cold tier
    c.put("a", 1)
    c.put("b", 2)                                            # 'a' evicted, nowhere to spill
    assert c.get("a") is None and c.get("b") == 2
