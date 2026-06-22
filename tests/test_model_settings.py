# SPDX-License-Identifier: Apache-2.0
"""Per-model generation overrides: a persisted store, precedence (request >
per-model > global > fallback), the /api/model-settings endpoints, and the
approximate max_context_window guard."""

from infermesh.core.model_settings import ModelSettingsStore


def test_store_set_get_clear_persist(tmp_path):
    p = tmp_path / "ms.json"
    s = ModelSettingsStore(path=p)
    s.set("m", temperature=0.3, max_tokens=64)
    assert s.get("m") == {"temperature": 0.3, "max_tokens": 64}
    s.set("m", temperature=None)                       # null clears just that field
    assert s.get("m") == {"max_tokens": 64}
    assert ModelSettingsStore(path=p).get("m") == {"max_tokens": 64}   # persisted across instances
    s.set("m", max_tokens=None)                         # last field gone -> model dropped
    assert s.get("m") == {} and "m" not in s.all()


def test_apply_model_overrides_precedence(tmp_path):
    from infermesh.server import _apply_model_overrides, _apply_gen_defaults
    from infermesh.core.settings import Settings
    from infermesh.api.openai_models import ChatCompletionRequest
    store = ModelSettingsStore(path=tmp_path / "ms.json")
    store.set("m", temperature=0.2, top_p=0.5)
    msgs = [{"role": "user", "content": "hi"}]

    req = ChatCompletionRequest(model="m", messages=msgs)
    _apply_model_overrides(req, "m", store)
    _apply_gen_defaults(req, Settings(gen_temperature=0.9, gen_top_k=40))
    assert req.temperature == 0.2 and req.top_p == 0.5   # per-model won over global 0.9
    assert req.top_k == 40                                # global filled what per-model didn't set

    req2 = ChatCompletionRequest(model="m", messages=msgs, temperature=1.5)
    _apply_model_overrides(req2, "m", store)
    assert req2.temperature == 1.5                        # explicit request value still wins


def test_api_model_settings_roundtrip_and_clamp(client, monkeypatch):
    import infermesh.server as srv
    monkeypatch.setattr(srv._MODEL_SETTINGS, "_save", lambda: None)   # keep tests off ~/.infermesh
    r = client.put("/api/model-settings",
                   json={"model": "echo-1", "temperature": 9.9, "max_context_window": 4096}).json()
    assert r["settings"]["temperature"] == 2.0 and r["settings"]["max_context_window"] == 4096   # clamped
    allm = client.get("/api/model-settings").json()["settings"]
    assert "echo-1" in allm and allm["echo-1"]["max_context_window"] == 4096
    client.put("/api/model-settings", json={"model": "echo-1", "temperature": None, "max_context_window": None})
    assert "echo-1" not in client.get("/api/model-settings").json()["settings"]   # cleared -> dropped


def test_max_context_window_rejects_long_prompt(client, monkeypatch):
    import infermesh.server as srv
    monkeypatch.setattr(srv._MODEL_SETTINGS, "_save", lambda: None)
    client.put("/api/model-settings", json={"model": "echo-1", "max_context_window": 5})  # ~5 tokens
    long = "word " * 50                                  # ~250 chars -> ~62 est. tokens
    r = client.post("/v1/chat/completions",
                    json={"model": "echo-1", "messages": [{"role": "user", "content": long}]})
    assert r.status_code == 400
    assert "context_too_long" in client.get("/api/stats?scope=session").json()["rejections"]
    client.put("/api/model-settings", json={"model": "echo-1", "max_context_window": None})   # cleanup
