# SPDX-License-Identifier: Apache-2.0
"""Built-in bilingual Guide page + real version in the sidebar (Milestone 3)."""

from infermesh.dashboard import DASHBOARD_HTML


def test_guide_page_present():
    """Nav entry + section + the four tutorial topics the guide must cover:
    install (pipx), GPU hookup, model hookup, team shared library."""
    for marker in ('data-sec="guide"', 'id="sec-guide"', "guide:'Guide'",
                   "pipx install infermesh", "nvidia-smi", "--backend",
                   "--model-dir", 'data-i18n="Guide"'):
        assert marker in DASHBOARD_HTML, marker


def test_dashboard_shows_real_version(client):
    from infermesh import __version__

    html = client.get("/").text
    assert f"v{__version__}" in html
    assert "__INFERMESH_VERSION__" not in html   # placeholder must be substituted
