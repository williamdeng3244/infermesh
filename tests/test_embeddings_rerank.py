# SPDX-License-Identifier: Apache-2.0
"""Embeddings + rerank endpoints and mock implementation (Milestone 2)."""

import base64


def test_embeddings_float_shape(client):
    r = client.post("/v1/embeddings", json={
        "model": "echo-1",
        "input": ["hello world", "foo bar baz"],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    assert data["model"] == "echo-1"
    assert len(data["data"]) == 2
    assert data["data"][0]["object"] == "embedding"
    assert [d["index"] for d in data["data"]] == [0, 1]
    vec = data["data"][0]["embedding"]
    assert isinstance(vec, list) and len(vec) >= 1
    assert all(isinstance(x, (int, float)) for x in vec)
    assert data["usage"]["prompt_tokens"] >= 1
    assert data["usage"]["total_tokens"] == data["usage"]["prompt_tokens"]


def test_embeddings_deterministic_and_single_input(client):
    r1 = client.post("/v1/embeddings", json={"model": "echo-1", "input": "same text"})
    r2 = client.post("/v1/embeddings", json={"model": "echo-1", "input": "same text"})
    assert len(r1.json()["data"]) == 1  # single string -> one vector
    assert r1.json()["data"][0]["embedding"] == r2.json()["data"][0]["embedding"]


def test_embeddings_base64_and_dimensions(client):
    rb = client.post("/v1/embeddings", json={
        "model": "echo-1", "input": "hi", "encoding_format": "base64",
    })
    emb = rb.json()["data"][0]["embedding"]
    assert isinstance(emb, str)
    raw = base64.b64decode(emb)
    assert len(raw) % 4 == 0  # little-endian float32 bytes

    rd = client.post("/v1/embeddings", json={
        "model": "echo-1", "input": "hi", "dimensions": 4,
    })
    assert len(rd.json()["data"][0]["embedding"]) == 4


def test_rerank_orders_by_overlap(client):
    r = client.post("/v1/rerank", json={
        "model": "echo-1",
        "query": "cat dog",
        "documents": ["unrelated text", "cat dog bird", "cat only"],
    })
    assert r.status_code == 200
    results = r.json()["results"]
    scores = [x["relevance_score"] for x in results]
    assert scores == sorted(scores, reverse=True)          # sorted descending
    assert results[0]["index"] == 1                         # "cat dog bird" shares both words
    assert results[0]["document"] == {"text": "cat dog bird"}


def test_rerank_top_n_and_return_documents(client):
    r = client.post("/v1/rerank", json={
        "model": "echo-1",
        "query": "q",
        "documents": ["a", "b", "c", "d"],
        "top_n": 2,
        "return_documents": False,
    })
    results = r.json()["results"]
    assert len(results) == 2
    assert results[0]["document"] is None


async def test_mock_embed_rerank_units():
    from infermesh.backends.mock.mock_backend import MockEchoBackend
    from infermesh.core.backend import ModelSpec

    b = MockEchoBackend()
    await b.load(ModelSpec(model_id="m", source="/tmp/m", extra={"embed_dim": 8}))
    vecs = await b.embed(["x", "x", "y"])
    assert len(vecs[0]) == 8 and vecs[0] == vecs[1] and vecs[0] != vecs[2]
    scores = await b.rerank("a b", ["a b c", "a", "z"])
    assert scores[0] > scores[1] > scores[2]
