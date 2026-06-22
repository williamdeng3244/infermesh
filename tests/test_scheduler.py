# SPDX-License-Identifier: Apache-2.0
"""Admission control (control-plane concurrency cap): the gate caps in-flight
requests, queues the excess, and rejects (Overloaded -> 503) when the queue is
full or the wait times out. /api/status exposes it; PUT adjusts it live."""

import asyncio

import pytest

from infermesh.core.scheduler import AdmissionController, Overloaded


async def test_cap_enforced_and_release_wakes_waiter():
    g = AdmissionController(cap=2)
    await g.acquire()
    await g.acquire()
    assert g.snapshot()["active"] == 2
    task = asyncio.ensure_future(g.acquire())          # 3rd must block
    await asyncio.sleep(0.05)
    assert not task.done() and g.snapshot()["waiting"] == 1
    await g.release()                                  # frees a slot -> waiter proceeds
    await asyncio.wait_for(task, 1)
    assert g.snapshot()["active"] == 2 and g.snapshot()["waiting"] == 0


async def test_overload_rejects_when_queue_full():
    g = AdmissionController(cap=1, max_queue=1)
    await g.acquire()                                  # active=1 (full)
    waiter = asyncio.ensure_future(g.acquire())        # waiting=1 (queue now full)
    await asyncio.sleep(0.05)
    assert g.snapshot()["waiting"] == 1
    with pytest.raises(Overloaded):
        await g.acquire()                              # queue full -> reject immediately
    await g.release()                                  # let the queued one through
    await asyncio.wait_for(waiter, 1)
    await g.release()


async def test_admission_wait_times_out():
    g = AdmissionController(cap=1, timeout=0.05)
    await g.acquire()
    with pytest.raises(Overloaded):
        await g.acquire()                              # waits ~50ms, then 503
    await g.release()


async def test_configure_raises_cap_live():
    g = AdmissionController(cap=1)
    await g.acquire()
    g.configure(cap=2)                                 # raise the cap at runtime
    await asyncio.wait_for(g.acquire(), 1)             # second slot now available
    assert g.snapshot()["active"] == 2


def test_api_status_exposes_admission(client):
    adm = client.get("/api/status").json()["admission"]
    assert adm["cap"] >= 1 and adm["active"] == 0 and "waiting" in adm


def test_settings_put_concurrency_is_live(client, monkeypatch):
    from infermesh.core.settings import Settings
    monkeypatch.setattr(Settings, "save", lambda self, *a, **k: None)
    r = client.put("/api/settings", json={"max_concurrent_requests": 3, "max_queued_requests": 5}).json()
    assert "max_concurrent_requests" in r["updated"] and "max_queued_requests" in r["updated"]
    assert client.get("/api/status").json()["admission"]["cap"] == 3    # applied to the live gate


def test_chat_returns_503_and_records_rejection_when_overloaded(client, monkeypatch):
    async def _overloaded():
        raise Overloaded(8, 8)
    monkeypatch.setattr(client.app.state.gate, "acquire", _overloaded)   # force capacity reached
    r = client.post("/v1/chat/completions",
                    json={"model": "echo-1", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503
    assert "overloaded" in client.get("/api/stats?scope=session").json()["rejections"]
