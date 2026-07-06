# SPDX-License-Identifier: Apache-2.0
"""Dashboard i18n coverage + new-page markers (Milestone 2, commit 9).

The dashboard's i18n uses English text as the key: T('...') falls back to the
key itself, so a key missing from I18N silently ships untranslated Chinese UI.
This test parses the shipped script and asserts every literal T() argument and
every data-i18n attribute has an I18N entry — the check the design package
asked to fold into CI (docs/design/design-and-porting-notes.zh.md §4).
"""

import html
import re

from infermesh.dashboard import DASHBOARD_HTML


def _script() -> str:
    return "\n".join(re.findall(r"<script>(.*?)</script>", DASHBOARD_HTML, re.S))


def _i18n_keys(src: str) -> set:
    keys: set = set()
    # const I18N={...}; plus any Object.assign(I18N,{...}); block
    for m in re.finditer(r"(?:const I18N=\{|Object\.assign\(I18N,\{)(.*?)\}\)?;", src, re.S):
        keys |= set(re.findall(r'"((?:[^"\\]|\\.)+)"\s*:', m.group(1)))
    return keys


def _used_keys(src: str) -> set:
    used = set(re.findall(r"""\bT\('((?:[^'\\]|\\.)+)'\)""", src))
    used |= set(re.findall(r'''\bT\("((?:[^"\\]|\\.)+)"\)''', src))
    # attributes are entity-encoded in the source; the runtime walker sees
    # them decoded (getAttribute), so decode before matching dict keys
    used |= {html.unescape(k) for k in re.findall(r'data-i18n="([^"]+)"', DASHBOARD_HTML)}
    return used


def test_every_ui_string_has_a_translation():
    src = _script()
    defined = _i18n_keys(src)
    assert len(defined) > 150, "I18N dict failed to parse"
    used = _used_keys(src)
    assert used, "no T()/data-i18n usages found — extraction broke"
    missing = sorted(k for k in used if k not in defined)
    assert not missing, f"untranslated UI keys ({len(missing)}): {missing[:20]}"


def test_analysis_and_compare_pages_present():
    for marker in ('id="sec-analysis"', 'id="sec-compare"',
                   'data-sec="analysis"', 'data-sec="compare"',
                   'id="anRoot"', 'id="cpRoot"', 'id="tt"'):
        assert marker in DASHBOARD_HTML, marker
    src = _script()
    for fn in ("rooflineSVG", "frontierSVG", "scalingSVG", "timelineSVG",
               "pctBarsSVG", "bindTTs", "loadAnalysis", "loadCompare"):
        assert re.search(rf"function {fn}\(", src), fn
    # the new pages talk to the read-side analysis APIs, not mock data
    for ep in ("/api/analysis/efficiency", "/api/analysis/frontier",
               "/api/analysis/scaling", "/api/analysis/timeline",
               "/api/compare", "/api/specs"):
        assert ep in src, ep


def test_no_external_urls_in_dashboard():
    # zero-CDN rule: the page must render offline (GCU deployments are walled)
    assert not re.search(r'src="https?://|href="https?://', DASHBOARD_HTML)
    assert "@import" not in DASHBOARD_HTML
