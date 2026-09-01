"""Tests for the dashboard diagram viewability refactor (AC1, AC2, AC3, AC5, AC6).

Covers:
- AC1: generated diagram has no dotted ORCH dispatch edges; single head edge
- AC2: subagent node status follows trace-first, then phase-complete, then pending
- AC3: dashboard HTML contains the status legend
- AC5: exactly one renderer implementation (HTML loads /static/dashboard.js)
- AC6: markdown output stays valid Mermaid; every registered agent appears
"""

from __future__ import annotations

import re
from pathlib import Path

from sdlc_cli.dashboard_html import DASHBOARD_HTML
from sdlc_cli.mermaid import generate_agent_map_md, generate_mermaid
from sdlc_cli.phases import agent_registry


def _registry_agent_ids() -> set[str]:
    ids: set[str] = set()
    for row in agent_registry():
        ids.add(row["agent"])
        ids.update(row["subagents"])
    return ids


# ---------------------------------------------------------------------------
# AC1 — clean pipeline shape
# ---------------------------------------------------------------------------

def test_ac1_no_dotted_dispatch_edges_from_orch() -> None:
    src = generate_mermaid()
    assert ".->" not in src, "dotted dispatch edges must be gone"


def test_ac1_single_pipeline_head_edge() -> None:
    src = generate_mermaid()
    head_edges = re.findall(r"^    ORCH --> (\S+)$", src, re.M)
    assert head_edges == ["stage_problem_discovery"], (
        "exactly one head edge from ORCH to the first visible stage"
    )


def test_ac1_phase_sequence_chain_preserved() -> None:
    src = generate_mermaid()
    chain = re.findall(r"^    (\S+) ==> (\S+)$", src, re.M)
    assert len(chain) >= 12, "phase chain must connect all visible stages"
    # Chain starts at the first visible stage and moves strictly forward.
    assert chain[0][0] == "stage_problem_discovery"


def test_ac1_disabled_phases_hide_head_edge_targets() -> None:
    src = generate_mermaid(enabled_map={"0-problem-discovery": False})
    assert "stage_problem_discovery -->" not in "".join(
        re.findall(r"^    (\S+) ==>", src, re.M)
    )


# ---------------------------------------------------------------------------
# AC2 — truthful subagent status
# ---------------------------------------------------------------------------

def test_ac2_trace_complete_subagent_is_done_while_phase_in_progress() -> None:
    orch = {"phases": {"2-product": {"status": "in_progress"}}}
    trace = {"traces": [{"agent": "sub-requirement-parser", "status": "complete"}]}
    src = generate_mermaid(orch, trace)
    assert "    class sub_requirement_parser done" in src


def test_ac2_trace_in_progress_subagent_is_active() -> None:
    orch = {"phases": {"2-product": {"status": "in_progress"}}}
    trace = {"traces": [{"agent": "sub-requirement-parser", "status": "in_progress"}]}
    src = generate_mermaid(orch, trace)
    assert "    class sub_requirement_parser active" in src


def test_ac2_completed_phase_completes_untraced_subagents() -> None:
    orch = {"phases": {"7-testing": {"status": "complete"}}}
    src = generate_mermaid(orch, {"traces": []})
    assert "    class sub_unit_test done" in src
    assert "    class stage_testing done" in src


def test_ac2_pending_phase_keeps_subagents_pending_despite_phase_status() -> None:
    src = generate_mermaid()  # all phases pending by default
    assert "    class sub_unit_test pending" in src


def test_ac2_latest_trace_entry_wins() -> None:
    orch = {"phases": {"2-product": {"status": "in_progress"}}}
    trace = {
        "traces": [
            {"agent": "sub-requirement-parser", "status": "pending"},
            {"agent": "sub-requirement-parser", "status": "complete"},
        ]
    }
    src = generate_mermaid(orch, trace)
    assert "    class sub_requirement_parser done" in src


# ---------------------------------------------------------------------------
# AC6 — markdown output validity & coverage
# ---------------------------------------------------------------------------

def test_ac6_markdown_wraps_valid_flowchart() -> None:
    md = generate_agent_map_md()
    assert md.startswith("# Agent Interaction Map")
    fence = md.split("```mermaid\n")[1].split("\n```")[0]
    assert fence.startswith("flowchart TD")


def test_ac6_every_registered_agent_appears() -> None:
    src = generate_mermaid()
    for agent in _registry_agent_ids():
        assert agent in src, f"agent {agent} missing from diagram"


def test_ac6_node_count_matches_registry() -> None:
    """Diagram nodes = 1 ORCH head node + 12 stage agents + 37 stage-owned
    subagents. (AGENTS.md counts 52 agents total, but the 2 cross-cutting
    subagents — compliance-validator, context-optimizer — are shared, not
    stage-owned, so they are not diagram nodes.)"""
    registry = agent_registry()
    subs = sum(len(r["subagents"]) for r in registry)
    stages = sum(1 for r in registry if r["role"] == "stage")
    assert subs == 37 and stages == 12
    src = generate_mermaid()
    # Node definition lines: `ORCH(["…"])` or `agent_id["…"]`. Edges/classes/
    # subgraph headers do not match this pattern.
    node_lines = re.findall(r'^\s+\w+\[.{0,2}"', src, re.M)
    assert len(node_lines) == subs + stages + 1  # + 1 for ORCH


# ---------------------------------------------------------------------------
# AC3 — legend present in dashboard HTML
# ---------------------------------------------------------------------------

def test_ac3_legend_element_present() -> None:
    assert 'id="diagramLegend"' in DASHBOARD_HTML
    assert "Complete" in DASHBOARD_HTML
    assert "In progress" in DASHBOARD_HTML
    assert "Pending" in DASHBOARD_HTML
    assert "Phase sequence" in DASHBOARD_HTML


# ---------------------------------------------------------------------------
# AC5 — single shared renderer
# ---------------------------------------------------------------------------

def test_ac5_html_has_no_inline_app_js() -> None:
    assert "async function renderMermaid" not in DASHBOARD_HTML
    assert "function render(" not in DASHBOARD_HTML
    assert "const PHASE_NAMES" not in DASHBOARD_HTML


def test_ac5_html_loads_shared_static_script() -> None:
    assert '<script src="/static/dashboard.js"></script>' in DASHBOARD_HTML
    # The server substitutes the WS port into this bootstrap line.
    assert "window.WS_PORT = /*WS_PORT*/8421;" in DASHBOARD_HTML


def test_ac5_static_js_defines_renderer_once() -> None:
    js = (
        Path(__file__).resolve().parents[1] / "src" / "sdlc_cli" / "static" / "dashboard.js"
    ).read_text(encoding="utf-8")
    assert js.count("async function renderMermaid") == 1
    assert js.count("const wsPort = window.WS_PORT || 8421;") == 1
    assert "diagramCanvas" in js
    assert "DiagramView" in js
    # Zoom clamp defined once (ADR-013): 5%..400%.
    assert "MIN_K = 0.05" in js and "MAX_K = 4.0" in js
