"""DOM-level checks for the Claude usage extractor.

The extractor is JavaScript injected into the webview, so the Python provider
tests exercise only its *output* shape. These tests run the real script under
Node against a mocked usage dialog, which is the only place row-matching bugs
can be caught. Skipped when Node is unavailable; GitHub's runners all ship it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from aiusageclock.providers.claude import EXTRACTOR_JS
from aiusageclock.providers.claude import extractor_js

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js not available"
)

# Note: the elements of this flat harness have no querySelectorAll, so once the
# extractor reaches its Fable expansion logic it throws inside the try/catch
# there and falls back to the plain reading (fable_expand == 'error'). These
# older cases only assert on the readings, which is why that is harmless.
HARNESS = """
const fs = require('fs');
const nodes = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const elements = nodes.map(([text, height]) => ({
  textContent: text,
  getBoundingClientRect: () => ({ height }),
}));
global.document = {
  body: { textContent: nodes[0][0] },
  title: 'Claude',
  querySelectorAll: (sel) => (sel.includes('a[href') ? [] : elements),
  querySelector: () => null,
};
global.location = {
  href: 'https://claude.ai/new#settings/usage',
  pathname: '/new',
  hash: '#settings/usage',
  hostname: 'claude.ai',
};
const result = eval(fs.readFileSync(process.argv[3], 'utf8'));
process.stdout.write(JSON.stringify(result));
"""

SESSION = "Current session Resets in 3 hr 10 min 18% used"
ALL_MODELS = "All models Resets in 22 hr 0 min 2% used"
FABLE = "Fable Resets in 22 hr 0 min 4% used"
IDLE_SESSION = "Current session Starts when a message is sent 0% used"
NEW_IDLE_SESSION = "Current session Starts with your first message 0% used"
PAUSED_SESSION = "Current session Paused until your week resets 8% used"
IDLE_FABLE = "Fable You haven’t used Fable yet 0% used"
LIVE_WEEKLY = "All models Resets Mon 5:59 PM 2% used"
NEW_SESSION = "Current session Resets at 11:00 PM 12% used"
NEW_WEEKLY = "This week Resets Monday 6:00 PM 77% used"
NEW_FABLE = (
    "Fable this week Separate weekly limit for Fable · "
    "Resets Monday 6:00 PM 63% used"
)
# Real banner text from the Max-plan usage dialog. It names Fable but is not a
# usage row, and it sits directly above the bars.
BANNER = (
    "Fable 5 is still included with your Max plan. If you see a prompt to "
    "set up usage credits for it, restart Claude Code."
)


def run_extractor(tmp_path, rows: list[tuple[str, int]]) -> dict:
    """Run EXTRACTOR_JS against a mock DOM. rows are (text, height) pairs.

    The first row stands in for the page wrapper and supplies document.body
    text, matching how the real page nests every row inside it.
    """
    harness = tmp_path / "harness.js"
    script = tmp_path / "extractor.js"
    nodes = tmp_path / "nodes.json"
    harness.write_text(HARNESS, encoding="utf-8")
    script.write_text(EXTRACTOR_JS, encoding="utf-8")
    nodes.write_text(json.dumps(rows), encoding="utf-8")
    out = subprocess.run(
        ["node", str(harness), str(nodes), str(script)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def percents(result: dict) -> dict:
    return {
        key: (result[key] or {}).get("percent")
        for key in ("session", "weekly_all", "weekly_fable")
    }


def test_login_route_without_login_link_reports_signed_out(tmp_path):
    """Claude's /new → /logout → /login redirect must not loop back to /new."""
    harness = tmp_path / "harness.js"
    script = tmp_path / "extractor.js"
    nodes = tmp_path / "nodes.json"
    harness.write_text(
        HARNESS.replace("https://claude.ai/new#settings/usage", "https://claude.ai/login")
        .replace("pathname: '/new'", "pathname: '/login'")
        .replace("hash: '#settings/usage'", "hash: ''"),
        encoding="utf-8",
    )
    script.write_text(EXTRACTOR_JS, encoding="utf-8")
    nodes.write_text(json.dumps([("Welcome back Sign in with Google", 900)]), encoding="utf-8")
    result = json.loads(subprocess.check_output(
        ["node", str(harness), str(nodes), str(script)], text=True
    ))
    assert result["logged_out"] is True
    assert "__retry_after_ms" not in result
    assert result["url"] == "https://claude.ai/login"


def test_sign_in_page_on_new_route_reports_signed_out(tmp_path):
    harness = tmp_path / "harness.js"
    script = tmp_path / "extractor.js"
    nodes = tmp_path / "nodes.json"
    harness.write_text(
        HARNESS.replace("title: 'Claude'", "title: 'Sign in - Claude'"),
        encoding="utf-8",
    )
    script.write_text(EXTRACTOR_JS, encoding="utf-8")
    nodes.write_text(json.dumps([("Welcome back Sign in with Google", 900)]), encoding="utf-8")
    result = json.loads(subprocess.check_output(
        ["node", str(harness), str(nodes), str(script)], text=True
    ))
    assert result["logged_out"] is True
    assert "__retry_after_ms" not in result


def test_max_plan_layout_reads_all_three_rows(tmp_path):
    wrapper = " ".join(
        ["Plan usage limits Max (5x)", SESSION, "Weekly limits", BANNER, ALL_MODELS, FABLE]
    )
    result = run_extractor(
        tmp_path,
        [
            (wrapper, 900),
            (SESSION, 60),
            (" ".join([BANNER, ALL_MODELS, FABLE]), 400),
            (BANNER, 90),
            (ALL_MODELS, 60),
            (FABLE, 60),
        ],
    )

    assert percents(result) == {"session": 18, "weekly_all": 2, "weekly_fable": 4}
    assert result["weekly_fable"]["reset_text"] == "22 hr 0 min"


def test_renamed_september_2026_usage_rows(tmp_path):
    """Claude's new dialog calls the weekly rows This week/Fable this week."""
    wrapper = " ".join(
        [
            "Your usage Max (5x)",
            "Heads up. At this pace you’ll run out tomorrow evening.",
            NEW_SESSION,
            NEW_WEEKLY,
            NEW_FABLE,
            "Usage credits",
        ]
    )
    result = run_extractor(
        tmp_path,
        [
            (wrapper, 1100),
            (NEW_SESSION, 60),
            (NEW_WEEKLY, 60),
            (NEW_FABLE, 90),
        ],
    )

    assert percents(result) == {
        "session": 12,
        "weekly_all": 77,
        "weekly_fable": 63,
    }
    assert result["session"]["reset_text"] == "at 11:00 PM"
    assert result["weekly_all"]["reset_text"] == "Monday 6:00 PM"
    assert result["weekly_fable"]["reset_text"] == "Monday 6:00 PM"
    assert "__retry_after_ms" not in result


# Real usage-page text as seen in textContent: no whitespace between elements.
# The Fable row carries a description ("Up to 50% of your weekly limit") that
# must never be read as usage.
CONCAT_SESSION = "Current sessionResets at 10:40 PM6% used"
CONCAT_WEEKLY = "This weekResets Tuesday 9:00 AM19% used"
CONCAT_FABLE_HEAD = "FableUp to 50% of your weekly limitResets Tuesday 9:00 AM"
CONCAT_FABLE = CONCAT_FABLE_HEAD + "18% used"
CONCAT_TAIL = "Limit resetsNo resets right now"


def test_concatenated_fable_row_ignores_the_description_percentage(tmp_path):
    """A child element holding only "…Up to 50%…Resets…" is shorter than the
    full row. It used to win and report the description's 50 as usage."""
    wrapper = CONCAT_SESSION + CONCAT_WEEKLY + CONCAT_FABLE + CONCAT_TAIL
    result = run_extractor(
        tmp_path,
        [
            (wrapper, 900),
            (CONCAT_SESSION, 60),
            (CONCAT_WEEKLY, 60),
            (CONCAT_FABLE_HEAD, 40),
            (CONCAT_FABLE, 90),
            (CONCAT_FABLE + CONCAT_TAIL, 130),
        ],
    )

    assert percents(result) == {"session": 6, "weekly_all": 19, "weekly_fable": 18}
    assert result["weekly_fable"]["kind"] == "used"
    assert result["weekly_fable"]["reset_text"] == "Tuesday 9:00 AM"
    assert result["weekly_all"]["reset_text"] == "Tuesday 9:00 AM"
    assert result["session"]["reset_text"] == "at 10:40 PM"


def test_complete_fable_row_beats_the_shorter_truncated_candidate(tmp_path):
    # Listed shortest-first on purpose: element order must not matter.
    result = run_extractor(
        tmp_path,
        [
            (CONCAT_SESSION + CONCAT_WEEKLY + CONCAT_FABLE, 900),
            (CONCAT_SESSION, 60),
            (CONCAT_WEEKLY, 60),
            (CONCAT_FABLE_HEAD, 40),
            (CONCAT_FABLE, 90),
        ],
    )

    assert result["weekly_fable"]["raw"] == CONCAT_FABLE
    assert result["weekly_fable"]["percent"] == 18


def test_truncated_fable_candidate_alone_is_not_a_reading(tmp_path):
    """No used/remaining value anywhere: report no Fable row (so the expander
    logic still runs) rather than the description's 50."""
    result = run_extractor(
        tmp_path,
        [
            (CONCAT_SESSION + CONCAT_WEEKLY + CONCAT_FABLE_HEAD, 900),
            (CONCAT_SESSION, 60),
            (CONCAT_WEEKLY, 60),
            (CONCAT_FABLE_HEAD, 40),
        ],
    )

    assert percents(result) == {"session": 6, "weekly_all": 19, "weekly_fable": None}
    assert result["weekly_fable"] is None


def test_fable_row_inside_a_wrapper_is_not_affected_by_the_trailing_rows(tmp_path):
    """Only the wrapper holds the Fable row. The text after it ("Limit
    resets…") must not change the reading or the reset text."""
    wrapper = CONCAT_SESSION + CONCAT_WEEKLY + CONCAT_FABLE + CONCAT_TAIL
    result = run_extractor(
        tmp_path,
        [(wrapper, 900), (CONCAT_SESSION, 60), (CONCAT_WEEKLY, 60)],
    )

    assert percents(result) == {"session": 6, "weekly_all": 19, "weekly_fable": 18}
    assert result["weekly_fable"]["reset_text"] == "Tuesday 9:00 AM"


def test_spaced_fable_row_ignores_the_description_percentage(tmp_path):
    head = "Fable Up to 50% of your weekly limit · Resets Tuesday 9:00 AM"
    full = head + " 18% used"
    result = run_extractor(
        tmp_path,
        [
            (" ".join([SESSION, NEW_WEEKLY, full]), 900),
            (SESSION, 60),
            (NEW_WEEKLY, 60),
            (head, 40),
            (full, 90),
        ],
    )

    assert percents(result)["weekly_fable"] == 18
    assert result["weekly_fable"]["kind"] == "used"
    assert result["weekly_fable"]["reset_text"] == "Tuesday 9:00 AM"


@pytest.mark.parametrize(
    ("fable_row", "percent", "kind"),
    [
        ("Fable Resets Tuesday 9:00 AM 82% remaining", 82, "remaining"),
        ("Fable Resets Tuesday 9:00 AM remaining: 82%", 82, "remaining"),
        ("Fable Resets Tuesday 9:00 AM used 7.5%", 7.5, "used"),
    ],
)
def test_labelled_percentage_forms_are_all_read(tmp_path, fable_row, percent, kind):
    result = run_extractor(
        tmp_path,
        [
            (" ".join([SESSION, ALL_MODELS, fable_row]), 900),
            (SESSION, 60),
            (ALL_MODELS, 60),
            (fable_row, 60),
        ],
    )

    assert result["weekly_fable"]["percent"] == percent
    assert result["weekly_fable"]["kind"] == kind


@pytest.mark.parametrize(
    ("session_row", "percent", "kind"),
    [
        # A trailing number after the first labelled value is not a second one.
        ("Current session Resets in 2 hr 6% used 19%", 6, "used"),
        ("Current sessionResets in 2 hr18% usedLimit resets", 18, "used"),
        ("Current session Resets in 2 hr 82% remaining", 82, "remaining"),
        ("Current session Resets in 2 hr remaining: 82%", 82, "remaining"),
        ("Current session Resets in 2 hr used 7.5%", 7.5, "used"),
        ("Current sessionResets in 2 hr6% usedThis week", 6, "used"),
    ],
)
def test_one_labelled_value_is_read_without_phantom_matches(
    tmp_path, session_row, percent, kind
):
    result = run_extractor(
        tmp_path,
        [
            (" ".join([session_row, ALL_MODELS]), 900),
            (session_row, 60),
            (ALL_MODELS, 60),
        ],
    )

    assert result["session"]["percent"] == percent
    assert result["session"]["kind"] == kind


def test_bare_percentage_in_a_session_row_is_not_a_usage_value(tmp_path):
    row = "Current session Up to 50% of your weekly limit Resets in 2 hr"
    result = run_extractor(
        tmp_path,
        [(" ".join([row, ALL_MODELS]), 900), (row, 60), (ALL_MODELS, 60)],
    )

    assert percents(result)["session"] is None


def test_fable_banner_without_a_fable_row_is_not_read_as_a_row(tmp_path):
    """The banner names Fable but carries no usage of its own.

    A container holding the banner plus the All-models row must not be read as
    the Fable row — that would report the neighbouring row's percentage.
    """
    wrapper = " ".join(["Plan usage limits", SESSION, "Weekly limits", BANNER, ALL_MODELS])
    result = run_extractor(
        tmp_path,
        [
            (wrapper, 900),
            (SESSION, 60),
            (" ".join([BANNER, ALL_MODELS]), 300),
            (BANNER, 90),
            (ALL_MODELS, 60),
        ],
    )

    assert percents(result) == {"session": 18, "weekly_all": 2, "weekly_fable": None}


def test_plan_without_fable_row_still_reads_session_and_weekly(tmp_path):
    wrapper = " ".join(["Plan usage limits", SESSION, ALL_MODELS])
    result = run_extractor(
        tmp_path, [(wrapper, 900), (SESSION, 60), (ALL_MODELS, 60)]
    )

    assert percents(result) == {"session": 18, "weekly_all": 2, "weekly_fable": None}


def test_fable_row_is_found_when_only_nested_beside_the_banner(tmp_path):
    """No tight row element — the banner and the row share one container."""
    wrapper = " ".join(["Plan usage limits", SESSION, ALL_MODELS, BANNER, FABLE])
    result = run_extractor(
        tmp_path,
        [
            (wrapper, 900),
            (SESSION, 60),
            (ALL_MODELS, 60),
            (" ".join([BANNER, FABLE]), 130),
        ],
    )

    assert percents(result)["weekly_fable"] == 4


def test_versioned_fable_row_label_still_matches(tmp_path):
    versioned = "Fable 5 Resets in 22 hr 0 min 7% used"
    wrapper = " ".join(["Plan usage limits", SESSION, ALL_MODELS, versioned])
    result = run_extractor(
        tmp_path,
        [(wrapper, 900), (SESSION, 60), (ALL_MODELS, 60), (versioned, 60)],
    )

    assert percents(result)["weekly_fable"] == 7


def test_current_claude_idle_session_layout_reports_mixed_usage(tmp_path):
    wrapper = " ".join(
        [
            "Plan usage limits Max (5x)",
            IDLE_SESSION,
            "Weekly limits",
            BANNER,
            LIVE_WEEKLY,
            IDLE_FABLE,
        ]
    )
    result = run_extractor(
        tmp_path,
        [
            (wrapper, 1100),
            (IDLE_SESSION, 80),
            (" ".join([BANNER, LIVE_WEEKLY, IDLE_FABLE]), 400),
            (BANNER, 90),
            (LIVE_WEEKLY, 60),
            (IDLE_FABLE, 80),
        ],
    )

    assert percents(result) == {"session": 0, "weekly_all": 2, "weekly_fable": 0}
    assert result["session"]["reset_text"] is None
    assert result["weekly_all"]["reset_text"] == "Mon 5:59 PM"
    assert result["weekly_fable"]["reset_text"] is None
    assert "__retry_after_ms" not in result


def test_september_2026_idle_session_copy_is_ready_and_reports_zero(tmp_path):
    """The idle session row has no reset time but is fully hydrated."""
    wrapper = " ".join(
        [
            "Your usage Max (5x)",
            NEW_IDLE_SESSION,
            NEW_WEEKLY,
            NEW_FABLE,
            "Usage credits",
        ]
    )
    result = run_extractor(
        tmp_path,
        [
            (wrapper, 1100),
            (NEW_IDLE_SESSION, 80),
            (NEW_WEEKLY, 60),
            (NEW_FABLE, 90),
        ],
    )

    assert percents(result) == {
        "session": 0,
        "weekly_all": 77,
        "weekly_fable": 63,
    }
    assert result["session"]["reset_text"] is None
    assert result["session"]["kind"] == "used"
    assert "__retry_after_ms" not in result


def test_weekly_cap_pauses_session_without_making_the_dialog_look_incomplete(tmp_path):
    """A capped account keeps its Session percentage but replaces its reset copy."""
    capped_weekly = "This week Resets at 6:00 PM 100% used"
    live_fable = (
        "Fable this week Separate weekly limit for Fable · "
        "Resets at 6:00 PM 76% used"
    )
    wrapper = " ".join(
        [
            "Your usage Max (5x)",
            "Limit hit. You can send new messages when your week resets.",
            PAUSED_SESSION,
            capped_weekly,
            live_fable,
            "Usage credits",
        ]
    )

    result = run_extractor(
        tmp_path,
        [(wrapper, 1100), (PAUSED_SESSION, 80), (capped_weekly, 60), (live_fable, 90)],
    )

    assert percents(result) == {
        "session": 8,
        "weekly_all": 100,
        "weekly_fable": 76,
    }
    assert result["session"]["reset_text"] == "Paused until your week resets"
    assert "__retry_after_ms" not in result


def test_status_wording_can_change_when_rows_only_share_a_wrapper(tmp_path):
    """Labels and values, rather than exact prose, define a hydrated row."""
    session = "Current session Temporarily unavailable until allowance renewal 8% used"
    weekly = "This week Your plan renews Monday evening 100% used"

    result = run_extractor(tmp_path, [(f"Your usage {session} {weekly}", 400)])

    assert percents(result) == {
        "session": 8,
        "weekly_all": 100,
        "weekly_fable": None,
    }
    assert "__retry_after_ms" not in result


def test_nested_label_only_elements_do_not_beat_rows_with_values(tmp_path):
    """Claude renders headings separately inside the complete usage rows."""
    capped_weekly = "This week Resets at 6:00 PM 100% used"
    live_fable = (
        "Fable this week Separate weekly limit for Fable · "
        "Resets at 6:00 PM 76% used"
    )
    wrapper = " ".join(["Your usage", PAUSED_SESSION, capped_weekly, live_fable])

    result = run_extractor(
        tmp_path,
        [
            (wrapper, 900),
            ("Current session", 20),
            (PAUSED_SESSION, 80),
            ("This week", 20),
            (capped_weekly, 60),
            ("Fable this week", 20),
            (live_fable, 90),
        ],
    )

    assert percents(result) == {
        "session": 8,
        "weekly_all": 100,
        "weekly_fable": 76,
    }
    assert "__retry_after_ms" not in result


def test_idle_copy_overrides_neighbor_percentage_in_shared_container(tmp_path):
    shared = " ".join([IDLE_SESSION, LIVE_WEEKLY])

    result = run_extractor(tmp_path, [(shared, 100)])

    assert percents(result) == {
        "session": 0,
        "weekly_all": 2,
        "weekly_fable": None,
    }


def test_legacy_idle_panel_without_percentages_reports_zero_rows(tmp_path):
    idle = (
        "Plan usage limits Current session Resets when you next use this limit "
        "All models Resets when you next use this limit"
    )
    result = run_extractor(tmp_path, [(idle, 400)])

    assert percents(result) == {
        "session": 0,
        "weekly_all": 0,
        "weekly_fable": None,
    }


# ---------------------------------------------------------------------------
# Fable row expansion: a small DOM tree that reacts to click().
# ---------------------------------------------------------------------------

HARNESS_DYNAMIC = r"""
const fs = require('fs');
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const byId = {};
const order = [];
let clicks = 0;

function makeNode(item) {
  const attrs = {...(item.attrs || {})};
  const node = {
    id: item.id,
    tagName: String(item.tag || 'div').toUpperCase(),
    own: item.text || '',
    hidden: !!item.hidden,
    parent: null,
    parentId: item.parent || null,
    height: item.height == null ? 60 : item.height,
    attrs,
    children: [],
    actions: item.onClick || [],
    getAttribute: name => (attrs[name] == null ? null : String(attrs[name])),
    hasAttribute: name => attrs[name] != null,
    getBoundingClientRect: () => ({ height: node.height }),
    closest: sel => {
      if (sel !== 'a[href]') throw new Error('unsupported closest: ' + sel);
      for (let n = node; n; n = n.parent) {
        if (n.tagName === 'A' && n.attrs.href != null) return n;
      }
      return null;
    },
    click: () => {
      clicks += 1;
      for (const action of node.actions) {
        if (action.reveal) byId[action.reveal].hidden = false;
        else if (action.setAttr) {
          const [id, name, value] = action.setAttr;
          byId[id].attrs[name] = String(value);
        } else throw new Error('unsupported action');
      }
    },
  };
  Object.defineProperty(node, 'parentElement', { get: () => node.parent || document.body });
  Object.defineProperty(node, 'textContent', {
    get: () => [node.own, ...node.children.filter(c => !c.hidden).map(c => c.textContent)]
      .filter(Boolean).join(' '),
  });
  node.querySelectorAll = sel => select(sel, descendants(node));
  // item.throws: DOM methods on this node that raise, to exercise error paths.
  for (const method of item.throws || []) {
    node[method] = () => { throw new Error('boom from ' + method); };
  }
  return node;
}

function descendants(node) {
  const out = [];
  for (const child of node.children) {
    if (child.hidden) continue;
    out.push(child, ...descendants(child));
  }
  return out;
}

// Unsupported selectors throw so a typo cannot silently match nothing.
function select(sel, pool) {
  switch (sel) {
    case 'div, section, li':
      return pool.filter(n => ['DIV', 'SECTION', 'LI'].includes(n.tagName));
    case '*':
      return pool;
    case 'a[href*="/login"]':
      return pool.filter(n => n.tagName === 'A' && String(n.attrs.href || '').includes('/login'));
    default:
      throw new Error('unsupported selector: ' + sel);
  }
}

const body = { tagName: 'BODY', children: [], parent: null };
Object.defineProperty(body, 'textContent', {
  get: () => body.children.filter(c => !c.hidden).map(c => c.textContent).filter(Boolean).join(' '),
});
const document = { title: 'Claude', body };
for (const item of spec.nodes) {
  const node = makeNode(item);
  byId[item.id] = node;
  order.push(node);
}
for (const node of order) {
  const parent = node.parentId ? byId[node.parentId] : body;
  node.parent = node.parentId ? parent : null;
  parent.children.push(node);
}
document.querySelectorAll = sel => select(sel, descendants(body));
document.querySelector = sel => document.querySelectorAll(sel)[0] || null;
Object.assign(document, spec.docProps || {});
global.document = document;
global.location = {
  href: 'https://claude.ai/new#settings/usage',
  pathname: '/new',
  hash: '#settings/usage',
  hostname: 'claude.ai',
};
const source = fs.readFileSync(process.argv[3], 'utf8');
const results = [];
for (let attempt = 0; attempt < (spec.repeat || 1); attempt++) results.push(eval(source));
process.stdout.write(JSON.stringify({
  results,
  clicks,
  retries: document.__aiusageclockRetries || 0,
}));
"""

WEEKLY_VALUE = "Resets Monday 6:00 PM 77% used"
OPUS_ROW = "Opus 9% used"


def run_dynamic(
    tmp_path,
    nodes: list[dict],
    *,
    repeat: int = 1,
    doc_props: dict | None = None,
    script: str = EXTRACTOR_JS,
) -> dict:
    """Run the script `repeat` times in one document, like the scraper does.

    Returns {"results": [...], "clicks": n, "retries": n}.
    """
    harness = tmp_path / "harness_dynamic.js"
    source = tmp_path / "extractor.js"
    spec = tmp_path / "spec.json"
    harness.write_text(HARNESS_DYNAMIC, encoding="utf-8")
    source.write_text(script, encoding="utf-8")
    spec.write_text(
        json.dumps(
            {"nodes": nodes, "repeat": repeat, "docProps": doc_props or {}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = subprocess.run(
        ["node", str(harness), str(spec), str(source)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def max_plan_nodes(
    *,
    with_toggle: bool = True,
    toggle_text: str = "This week",
    toggle_attrs: dict | None = None,
    on_click: list[dict] | None = None,
    weekly_extra: list[dict] | None = None,
    weekly_first: list[dict] | None = None,
    session_extra: list[dict] | None = None,
    revealed: bool = False,
) -> list[dict]:
    """A Max-plan dialog whose This-week row hides the Fable row until expanded.

    The weekly row holds a collapsed aria-expanded button labelled "This week"
    (unless with_toggle is False, when the label is plain text as on a Pro
    plan). Clicking it reveals the Fable row and an "Opus 9% used" child that
    ends up inside the weekly container.
    """
    nodes: list[dict] = [
        {"id": "root", "text": "Your usage Max (5x)", "height": 900},
        {"id": "session", "parent": "root", "text": NEW_SESSION},
    ]
    nodes += session_extra or []
    if with_toggle:
        nodes += [
            {"id": "weekly", "parent": "root"},
            *(weekly_first or []),
            {
                "id": "toggle",
                "parent": "weekly",
                "tag": "button",
                "text": toggle_text,
                "attrs": toggle_attrs or {"aria-expanded": "false"},
                "onClick": on_click
                if on_click is not None
                else [
                    {"reveal": "fable"},
                    {"reveal": "opus"},
                    {"setAttr": ["toggle", "aria-expanded", "true"]},
                ],
            },
            {"id": "weekly-value", "parent": "weekly", "tag": "span", "text": WEEKLY_VALUE},
        ]
    else:
        nodes.append({"id": "weekly", "parent": "root", "text": f"This week {WEEKLY_VALUE}"})
    nodes += weekly_extra or []
    nodes += [
        {"id": "opus", "parent": "weekly", "hidden": not revealed, "text": OPUS_ROW},
        {"id": "fable", "parent": "root", "hidden": not revealed, "text": NEW_FABLE, "height": 90},
        {"id": "credits", "parent": "root", "text": "Usage credits"},
    ]
    return nodes


def test_show_fable_sentinel_appears_exactly_once():
    assert EXTRACTOR_JS.count("const SHOW_FABLE = true;") == 1


def test_collapsed_weekly_row_is_clicked_once_and_asks_for_a_retry(tmp_path):
    out = run_dynamic(tmp_path, max_plan_nodes())

    result = out["results"][0]
    assert out["clicks"] == 1
    assert result["__retry_after_ms"] > 0
    assert result["fable_expand"] == "clicked"
    assert result["weekly_fable"] is None
    assert out["retries"] == 1


def test_fable_row_is_read_after_the_expansion_without_a_second_click(tmp_path):
    out = run_dynamic(tmp_path, max_plan_nodes(), repeat=2)

    first, second = out["results"]
    assert "__retry_after_ms" in first
    assert out["clicks"] == 1
    assert "__retry_after_ms" not in second
    assert second["fable_expand"] == "expanded"
    assert percents(second) == {"session": 12, "weekly_all": 77, "weekly_fable": 63}
    assert second["weekly_fable"]["reset_text"] == "Monday 6:00 PM"


def test_plan_without_an_expander_is_never_clicked_or_delayed(tmp_path):
    out = run_dynamic(tmp_path, max_plan_nodes(with_toggle=False))

    result = out["results"][0]
    assert out["clicks"] == 0
    assert "__retry_after_ms" not in result
    assert result["fable_expand"] == "none"
    assert percents(result) == {"session": 12, "weekly_all": 77, "weekly_fable": None}
    assert out["retries"] == 0


def test_unresponsive_expander_waits_once_then_gives_up_with_a_probe(tmp_path):
    out = run_dynamic(tmp_path, max_plan_nodes(on_click=[]), repeat=3)

    first, second, third = out["results"]
    assert first["fable_expand"] == "clicked"
    assert second["fable_expand"] == "waiting"
    assert "__retry_after_ms" in second
    assert third["fable_expand"] == "gave_up"
    assert "__retry_after_ms" not in third
    assert 0 < len(third["fable_probe"]) <= 8
    assert third["fable_probe"][0] == {"tag": "button", "expanded": "false", "text": "This week"}
    assert out["clicks"] == 1
    assert out["retries"] == 2
    assert percents(third) == {"session": 12, "weekly_all": 77, "weekly_fable": None}


def test_already_expanded_control_is_never_collapsed(tmp_path):
    out = run_dynamic(tmp_path, max_plan_nodes(toggle_attrs={"aria-expanded": "true"}))

    assert out["clicks"] == 0
    assert "__retry_after_ms" not in out["results"][0]
    assert out["results"][0]["fable_expand"] == "none"


UNSAFE_WEEKLY_CONTROLS = [
    pytest.param(
        [{"id": "x", "parent": "weekly", "tag": "button", "text": "Upgrade",
          "attrs": {"aria-expanded": "false"}}],
        id="upgrade-button",
    ),
    pytest.param(
        [{"id": "x", "parent": "weekly", "tag": "button", "text": "Manage usage credits",
          "attrs": {"aria-expanded": "false"}}],
        id="manage-credits-button",
    ),
    pytest.param(
        [{"id": "x", "parent": "weekly", "tag": "button", "text": "This week",
          "attrs": {"aria-expanded": "false", "aria-label": "Upgrade your plan"}}],
        id="label-button-with-upgrade-aria-label",
    ),
    pytest.param(
        [{"id": "x", "parent": "weekly", "tag": "a", "text": "This week",
          "attrs": {"href": "/upgrade", "aria-expanded": "false"}}],
        id="link-labelled-this-week",
    ),
    pytest.param(
        [
            {"id": "wrap", "parent": "weekly", "tag": "a", "attrs": {"href": "/pricing"}},
            {"id": "x", "parent": "wrap", "tag": "button", "text": "This week",
             "attrs": {"aria-expanded": "false"}},
        ],
        id="button-inside-a-link",
    ),
    pytest.param(
        [{"id": "x", "parent": "weekly", "tag": "button", "text": "Fable this week",
          "attrs": {"aria-expanded": "false"}}],
        id="fable-labelled-button",
    ),
]


@pytest.mark.parametrize("extra", UNSAFE_WEEKLY_CONTROLS)
def test_unsafe_controls_in_the_weekly_row_are_not_clicked(tmp_path, extra):
    out = run_dynamic(tmp_path, max_plan_nodes(with_toggle=False, weekly_extra=extra))

    assert out["clicks"] == 0
    assert "__retry_after_ms" not in out["results"][0]
    assert percents(out["results"][0])["weekly_all"] == 77


def test_collapsed_control_in_the_session_row_is_not_clicked(tmp_path):
    session_button = [
        {"id": "session-toggle", "parent": "session", "tag": "button",
         "attrs": {"aria-expanded": "false"}},
    ]
    out = run_dynamic(
        tmp_path, max_plan_nodes(with_toggle=False, session_extra=session_button)
    )

    assert out["clicks"] == 0
    assert "__retry_after_ms" not in out["results"][0]
    assert percents(out["results"][0])["session"] == 12


def test_extractor_js_false_never_clicks_or_retries(tmp_path):
    out = run_dynamic(tmp_path, max_plan_nodes(), script=extractor_js(False))

    result = out["results"][0]
    assert out["clicks"] == 0
    assert "__retry_after_ms" not in result
    assert "fable_expand" not in result
    assert percents(result) == {"session": 12, "weekly_all": 77, "weekly_fable": None}


def test_no_click_once_the_retry_budget_is_spent(tmp_path):
    out = run_dynamic(
        tmp_path, max_plan_nodes(), doc_props={"__aiusageclockRetries": 4}
    )

    result = out["results"][0]
    assert out["clicks"] == 0
    assert "__retry_after_ms" not in result
    assert result["fable_expand"] == "budget"
    assert result["fable_probe"][0]["text"] == "This week"
    assert percents(result)["weekly_all"] == 77


def test_the_last_budgeted_retry_still_allows_the_click(tmp_path):
    out = run_dynamic(
        tmp_path, max_plan_nodes(), doc_props={"__aiusageclockRetries": 3}
    )

    assert out["clicks"] == 1
    assert out["results"][0]["fable_expand"] == "clicked"
    assert out["retries"] == 4


def test_waiting_for_the_fable_row_respects_the_retry_budget(tmp_path):
    out = run_dynamic(
        tmp_path,
        max_plan_nodes(on_click=[]),
        repeat=2,
        doc_props={"__aiusageclockRetries": 3},
    )

    first, second = out["results"]
    assert first["fable_expand"] == "clicked"
    assert second["fable_expand"] == "gave_up"
    assert "__retry_after_ms" not in second


def test_readings_taken_before_the_click_are_pinned(tmp_path):
    """Expanding adds an "Opus 9% used" child to the weekly container.

    Re-reading that container would report 9% as the weekly value.
    """
    out = run_dynamic(tmp_path, max_plan_nodes(), repeat=2)

    assert percents(out["results"][1]) == {
        "session": 12,
        "weekly_all": 77,
        "weekly_fable": 63,
    }

    # Control: without the pin the same expanded DOM does misread the weekly row.
    unpinned = run_dynamic(tmp_path, max_plan_nodes(with_toggle=False, revealed=True))
    assert percents(unpinned["results"][0])["weekly_all"] == 9


def test_not_ready_dialog_retries_are_counted(tmp_path):
    nodes = [{"id": "root", "text": "Your usage Loading", "height": 900}]

    out = run_dynamic(tmp_path, nodes, repeat=2)

    assert all(r["__retry_after_ms"] > 0 for r in out["results"])
    assert all(r["__retry_reason"] == "usage dialog not ready" for r in out["results"])
    assert out["retries"] == 2


def test_idle_weekly_row_without_percentages_is_still_expanded(tmp_path):
    nodes = [
        {"id": "root", "text": "Plan usage limits Max (5x)", "height": 900},
        {"id": "session", "parent": "root",
         "text": "Current session Resets when you next use this limit"},
        {"id": "weekly", "parent": "root"},
        {"id": "toggle", "parent": "weekly", "tag": "button", "text": "This week",
         "attrs": {"aria-expanded": "false"},
         "onClick": [{"setAttr": ["toggle", "aria-expanded", "true"]}]},
        {"id": "idle", "parent": "weekly", "tag": "span",
         "text": "Resets when you next use this limit"},
    ]

    out = run_dynamic(tmp_path, nodes)

    assert out["clicks"] == 1
    assert out["results"][0]["fable_expand"] == "clicked"


def test_pro_row_with_a_plain_label_span_is_not_clicked(tmp_path):
    """A heading span next to a value span is not an expander."""
    nodes = [
        {"id": "root", "text": "Your usage Pro", "height": 900},
        {"id": "session", "parent": "root", "text": NEW_SESSION},
        {"id": "weekly", "parent": "root"},
        {"id": "label", "parent": "weekly", "tag": "span", "text": "This week"},
        {"id": "value", "parent": "weekly", "tag": "span", "text": WEEKLY_VALUE},
    ]

    out = run_dynamic(tmp_path, nodes)

    result = out["results"][0]
    assert "fable_probe" not in result  # nothing control-like, so nothing to report
    assert out["clicks"] == 0
    assert "__retry_after_ms" not in result
    assert result["fable_expand"] == "none"
    assert out["retries"] == 0
    assert percents(result) == {"session": 12, "weekly_all": 77, "weekly_fable": None}


def test_popover_trigger_does_not_take_the_click_meant_for_the_expander(tmp_path):
    """An empty, collapsed, aria-haspopup trigger sits before the real toggle."""
    decoy = [
        {"id": "info", "parent": "weekly", "tag": "button",
         "attrs": {"aria-expanded": "false", "aria-haspopup": "dialog",
                   "aria-label": "More info"}},
    ]
    out = run_dynamic(tmp_path, max_plan_nodes(weekly_first=decoy), repeat=2)

    first, second = out["results"]
    assert first["fable_expand"] == "clicked"
    assert out["clicks"] == 1
    assert percents(second) == {"session": 12, "weekly_all": 77, "weekly_fable": 63}


@pytest.mark.parametrize(
    "attrs",
    [
        pytest.param({"aria-expanded": "false", "aria-label": "More info"}, id="more-info"),
        pytest.param(
            {"aria-expanded": "false", "aria-haspopup": "menu", "aria-label": "Show details"},
            id="haspopup-even-with-a-matching-label",
        ),
    ],
)
def test_empty_toggle_with_an_unrelated_or_popup_label_is_not_clicked(tmp_path, attrs):
    trigger = [{"id": "x", "parent": "weekly", "tag": "button", "attrs": attrs}]

    out = run_dynamic(tmp_path, max_plan_nodes(with_toggle=False, weekly_extra=trigger))

    assert out["clicks"] == 0
    assert "__retry_after_ms" not in out["results"][0]


@pytest.mark.parametrize(
    "label",
    # "Show budget details" contains "get" inside a word, which must not count
    # as the forbidden word "get".
    ["Show breakdown", "Expand", "This week details", "Show budget details", ""],
)
def test_empty_toggle_with_a_describing_or_no_label_is_clicked(tmp_path, label):
    attrs = {"aria-expanded": "false"}
    if label:
        attrs["aria-label"] = label
    toggle = [{
        "id": "x", "parent": "weekly", "tag": "button", "attrs": attrs,
        "onClick": [{"reveal": "fable"}, {"reveal": "opus"}],
    }]

    out = run_dynamic(
        tmp_path, max_plan_nodes(with_toggle=False, weekly_extra=toggle), repeat=2
    )

    assert out["clicks"] == 1
    assert percents(out["results"][1])["weekly_fable"] == 63


@pytest.mark.parametrize("attrs", [{"tabindex": "0"}, {"aria-controls": "details-panel"}])
def test_interactive_label_element_is_the_fallback_expander(tmp_path, attrs):
    label = [{
        "id": "x", "parent": "weekly", "tag": "div", "text": "This week", "attrs": attrs,
        "onClick": [{"reveal": "fable"}, {"reveal": "opus"}],
    }]

    out = run_dynamic(
        tmp_path, max_plan_nodes(with_toggle=False, weekly_extra=label), repeat=2
    )

    assert out["clicks"] == 1
    assert out["results"][0]["fable_expand"] == "clicked"
    assert percents(out["results"][1]) == {"session": 12, "weekly_all": 77, "weekly_fable": 63}


def test_unresolved_session_row_does_not_trap_the_expansion_in_not_ready_retries(tmp_path):
    """An idle panel with a session row the extractor cannot parse.

    The page is idle-zero (no percentages), so the weekly row gets expanded.
    The Fable row that appears brings a "0% used", which ends the idle-panel
    state while the pinned session row stays unresolved. The script must not
    fall back into "usage dialog not ready" retries until the scraper gives up.
    """
    nodes = [
        {"id": "root", "text": "Your usage Max (5x)", "height": 900},
        {"id": "session", "parent": "root", "text": "Current session Not started"},
        {"id": "weekly", "parent": "root"},
        {"id": "toggle", "parent": "weekly", "tag": "button", "text": "This week",
         "attrs": {"aria-expanded": "false"},
         "onClick": [{"reveal": "fable"}, {"setAttr": ["toggle", "aria-expanded", "true"]}]},
        {"id": "weekly-value", "parent": "weekly", "tag": "span",
         "text": "Resets when you next use this limit"},
        {"id": "fable", "parent": "root", "hidden": True,
         "text": "Fable this week You haven’t used Fable yet 0% used"},
        {"id": "credits", "parent": "root", "text": "Usage credits"},
    ]

    out = run_dynamic(tmp_path, nodes, repeat=6)
    baseline = run_dynamic(tmp_path, nodes, script=extractor_js(False))["results"][0]

    final = out["results"][-1]
    assert out["clicks"] == 1
    assert out["retries"] <= 3
    assert [r.get("__retry_reason") for r in out["results"]][1:] == [None] * 5
    assert "__retry_after_ms" not in final
    assert final["weekly_all"] is not None
    assert final["weekly_all"] == baseline["weekly_all"]
    assert final["weekly_fable"]["percent"] == 0


def test_weekly_row_without_a_container_reports_no_row(tmp_path):
    nodes = max_plan_nodes()
    next(n for n in nodes if n["id"] == "weekly")["height"] = 200  # not row-sized

    out = run_dynamic(tmp_path, nodes)

    result = out["results"][0]
    assert out["clicks"] == 0
    assert "__retry_after_ms" not in result
    assert result["fable_expand"] == "no_row"
    assert "fable_probe" not in result


def test_unrecognised_toggle_is_reported_with_a_probe(tmp_path):
    toggle = [{"id": "x", "parent": "weekly", "tag": "button",
               "attrs": {"aria-expanded": "false", "aria-label": "Toggle"}}]

    out = run_dynamic(tmp_path, max_plan_nodes(with_toggle=False, weekly_extra=toggle))

    result = out["results"][0]
    assert out["clicks"] == 0
    assert "__retry_after_ms" not in result
    assert result["fable_expand"] == "none"
    assert result["fable_probe"] == [{"tag": "button", "expanded": "false", "text": ""}]


def weekly_labels_in_js() -> list[str]:
    """The labels of the weekly group (second entry) of ROW_LABEL_GROUPS."""
    block = re.search(r"const ROW_LABEL_GROUPS = \[(.*?)\n  \];", EXTRACTOR_JS, re.S)
    assert block, "ROW_LABEL_GROUPS not found"
    groups = re.findall(r"\[([^\]]*)\]", re.sub(r"//[^\n]*", "", block.group(1)))
    return re.findall(r"'([^']*)'", groups[1])


def test_weekly_labels_under_test_match_the_extractor():
    assert sorted(weekly_labels_in_js()) == ["All models", "This week"]


@pytest.mark.parametrize("label", weekly_labels_in_js())
def test_expander_labelled_with_any_weekly_label_is_accepted(tmp_path, label):
    out = run_dynamic(tmp_path, max_plan_nodes(toggle_text=label), repeat=2)

    assert out["clicks"] == 1
    assert out["results"][0]["fable_expand"] == "clicked"
    assert percents(out["results"][1]) == {"session": 12, "weekly_all": 77, "weekly_fable": 63}


def test_dom_error_in_the_expansion_logic_keeps_the_plain_reading(tmp_path):
    nodes = max_plan_nodes()
    next(n for n in nodes if n["id"] == "toggle")["throws"] = ["getAttribute"]

    out = run_dynamic(tmp_path, nodes)

    result = out["results"][0]
    assert out["clicks"] == 0
    assert "__retry_after_ms" not in result
    assert result["fable_expand"] == "error"
    assert "boom from getAttribute" in result["fable_error"]
    assert percents(result) == {"session": 12, "weekly_all": 77, "weekly_fable": None}
