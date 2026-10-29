"""DevPilot Streamlit dashboard - live mission view, approval, and past runs."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Add devpilot root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="DevPilot",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }
    .stApp { background: #0f1117; color: #e2e8f0; }
    .metric-card {
        background: linear-gradient(135deg, #1e293b, #0f172a);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px;
        margin: 4px 0;
    }
    .agent-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 600;
        margin: 2px;
    }
    .pill-planner { background: #7c3aed; color: white; }
    .pill-developer { background: #2563eb; color: white; }
    .pill-verifier { background: #059669; color: white; }
    .pill-reviewer { background: #d97706; color: white; }
    .pill-orchestrator { background: #475569; color: white; }
    .status-met { color: #10b981; font-weight: 600; }
    .status-unmet { color: #6b7280; }
    .status-failed { color: #ef4444; font-weight: 600; }
    .blocked-badge {
        background: #7f1d1d;
        color: #fca5a5;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
    }
    .log-line {
        font-family: 'Courier New', monospace;
        font-size: 12px;
        padding: 3px 6px;
        border-left: 2px solid #334155;
        margin: 1px 0;
    }
    .log-blocked { border-left-color: #ef4444; background: #1a0f0f; }
    .log-tool { border-left-color: #3b82f6; }
    .log-agent { border-left-color: #8b5cf6; }
    div[data-testid="stExpander"] { border: 1px solid #334155; border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── State helpers ──────────────────────────────────────────────────────────────

def get_runs_dir() -> Path:
    return ROOT / "runs"


def list_run_logs() -> list[Path]:
    runs_dir = get_runs_dir()
    if not runs_dir.exists():
        return []
    return sorted(runs_dir.glob("run_*.jsonl"), reverse=True)


def load_log(log_path: Path) -> list[dict]:
    records = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except Exception:
        pass
    return records


def load_report(run_id: str) -> str:
    path = get_runs_dir() / f"{run_id}_report.md"
    if path.exists():
        return path.read_text()
    return ""


# ── Sidebar navigation ─────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("# 🚀 DevPilot")
    st.markdown("*Multi-Agent Code Change System*")
    st.divider()
    page = st.radio(
        "Navigate",
        ["🎯 Start Mission", "📡 Live View", "✅ Approval", "📁 Past Runs"],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("**Model:** " + os.getenv("MODEL", "claude-opus-4-5"))
    st.markdown("**Max Retries:** " + os.getenv("MAX_RETRIES", "3"))


# ── Page: Start Mission ────────────────────────────────────────────────────────

if page == "🎯 Start Mission":
    st.title("🎯 Start a Mission")
    st.markdown("Configure and launch a DevPilot code change mission.")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Repository")
        repo_options = [
            "demo_repos/mini_shop",
            "demo_repos/bugfix_repo",
            "demo_repos/failing_test_repo",
            "demo_repos/security_repo",
            "demo_repos/stuck_repo",
            "demo_repos/notools_repo",
            "demo_repos/revision_repo",
        ]
        repo_choice = st.selectbox("Select demo repo", repo_options)
        custom_repo = st.text_input("Or enter custom repo path")
        repo_path = custom_repo if custom_repo else str(ROOT / repo_choice)

        simulate_missing = st.text_input(
            "Simulate missing tool (optional)", placeholder="e.g. pytest"
        )

    with col2:
        st.subheader("Request")
        request_presets = {
            "Custom...": "",
            "Add SAVE10 coupon (10% off)": "Add coupon support. SAVE10 gives 10% off. Apply via cart.total_with_coupon('SAVE10').",
            "Fix off-by-one bug": "Fix the off-by-one bug in get_top_n so it returns exactly n items.",
            "Fix SQL injection + remove hardcoded password": "Fix SQL injection vulnerabilities in db.py using parameterized queries and remove the hardcoded password.",
            "Fix failing import": "Fix the failing test: add a say_hello alias or rename greet to say_hello in greeter.py.",
            "Change tax to 15%": "Change the tax rate in apply_tax from 10% to 15%.",
            "Add modulo function": "Add a modulo function to math_ops.py: modulo(a, b) returns a % b, raises ValueError if b == 0.",
            "Ambiguous request": "add a discount",
        }
        preset = st.selectbox("Preset request", list(request_presets.keys()))
        request = st.text_area(
            "Request",
            value=request_presets[preset],
            height=150,
            help="Plain-English description of the code change",
        )

    st.divider()

    if st.button("🚀 Launch Mission", type="primary", use_container_width=True):
        if not request.strip():
            st.error("Please enter a request.")
        elif not Path(repo_path).exists():
            st.error(f"Repo path not found: {repo_path}")
        else:
            st.session_state["last_repo"] = repo_path
            st.session_state["last_request"] = request
            st.session_state["mission_running"] = True
            st.session_state["mission_log"] = []
            st.session_state["run_id"] = None

            # Run in background thread
            def run_mission(repo: str, req: str, sim_missing: str | None):
                from core.orchestrator import Orchestrator
                import unittest.mock as mock

                orch = Orchestrator(
                    repo_path=Path(repo),
                    request=req,
                    simulate_missing=sim_missing or None,
                )
                st.session_state["run_id"] = orch.run_id
                with mock.patch("builtins.input", return_value="n"):
                    orch.run()
                st.session_state["mission_running"] = False
                st.session_state["orchestrator"] = orch

            thread = threading.Thread(
                target=run_mission,
                args=(repo_path, request, simulate_missing or None),
                daemon=True,
            )
            thread.start()
            st.session_state["mission_thread"] = thread
            st.success("Mission launched! Go to 📡 Live View to monitor progress.")


# ── Page: Live View ───────────────────────────────────────────────────────────

elif page == "📡 Live View":
    st.title("📡 Live Mission View")

    # Auto-refresh
    auto_refresh = st.toggle("Auto-refresh (3s)", value=True)
    if auto_refresh:
        time.sleep(3)
        st.rerun()

    run_id = st.session_state.get("run_id")
    if not run_id:
        # Try to find the latest run
        logs = list_run_logs()
        if logs:
            latest = logs[0]
            run_id = latest.stem
        else:
            st.info("No mission running. Start one from 🎯 Start Mission.")
            st.stop()

    log_path = get_runs_dir() / f"{run_id}.jsonl"
    records = load_log(log_path)

    # Header metrics
    col1, col2, col3, col4 = st.columns(4)
    agents_seen = {r.get("agent", "") for r in records}
    blocked_count = sum(1 for r in records if r.get("event_type") == "BLOCKED")
    tool_calls = sum(1 for r in records if r.get("event_type") == "TOOL_CALL")

    with col1:
        st.metric("Run ID", run_id[:12])
    with col2:
        st.metric("Log Events", len(records))
    with col3:
        st.metric("Tool Calls", tool_calls)
    with col4:
        st.metric("🚫 Blocked", blocked_count)

    running = st.session_state.get("mission_running", False)
    if running:
        st.info("⏳ Mission in progress...")
    else:
        st.success("✅ Mission complete")

    st.divider()

    # Agent timeline
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("📋 Agent Timeline")

        agent_colors = {
            "planner": "pill-planner",
            "developer": "pill-developer",
            "verifier": "pill-verifier",
            "reviewer": "pill-reviewer",
            "orchestrator": "pill-orchestrator",
        }

        for rec in records[-50:]:  # Show last 50 events
            agent = rec.get("agent", "?")
            event = rec.get("event_type", "")
            tool = rec.get("tool", "")
            inp = rec.get("input", "")[:40]
            out = rec.get("output_summary", "")[:60]
            timestamp = rec.get("time", "")[-8:-1] if rec.get("time") else ""

            is_blocked = event == "BLOCKED"
            css_class = "log-blocked" if is_blocked else ("log-tool" if tool else "log-agent")
            pill_class = agent_colors.get(agent, "pill-orchestrator")

            blocked_icon = "🚫 " if is_blocked else ""
            tool_str = f" [{tool}]" if tool else ""
            detail = f" {inp}" if inp else ""

            st.markdown(
                f'<div class="log-line {css_class}">'
                f'<span class="agent-pill {pill_class}">{agent}</span> '
                f'{blocked_icon}<strong>{event}</strong>{tool_str}{detail}'
                f'<span style="color:#6b7280;float:right">{timestamp}</span>'
                f"</div>",
                unsafe_allow_html=True,
            )

    with col_right:
        st.subheader("📊 Criteria")

        # Try to read criteria from orchestrator state if available
        orch = st.session_state.get("orchestrator")
        if orch:
            for c in orch.state.criteria:
                status_class = {
                    "met": "status-met",
                    "unmet": "status-unmet",
                    "failed": "status-failed",
                }.get(str(c.status), "status-unmet")
                icon = {"met": "✅", "unmet": "⏳", "failed": "❌"}.get(str(c.status), "⏳")
                st.markdown(
                    f'<div class="metric-card">'
                    f'{icon} <span class="{status_class}">{c.text[:80]}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("Criteria will appear after planning completes.")

        st.subheader("📨 Messages")
        if orch:
            msgs = orch.board.read_all()
            for m in msgs[-10:]:
                st.markdown(
                    f"**{m.type}** `{m.sender}→{m.receiver}`  \n"
                    + str(m.payload)[:100]
                )
        else:
            # Parse from log
            msg_events = [r for r in records if r.get("event_type") in (
                "PLAN_READY", "PLAN_REVISED", "TEST_FAILURE", "VERIFY_FINDING",
                "REVIEW_ISSUE", "CLARIFY", "ESCALATE", "BLOCKED", "TOOL_UNAVAILABLE"
            )]
            for r in msg_events[-10:]:
                icon = "🚫" if r.get("event_type") == "BLOCKED" else "📨"
                st.markdown(f"{icon} **{r['event_type']}** by `{r['agent']}`")

    # Test output
    if orch and orch.state.test_runs:
        st.subheader("🧪 Latest Test Output")
        latest_test = max(orch.state.test_runs, key=lambda t: t.timestamp)
        exit_icon = "✅" if latest_test.exit_code == 0 else "❌"
        st.markdown(f"{exit_icon} `{latest_test.command}` → exit {latest_test.exit_code}")
        st.code(latest_test.output[:2000], language="text")


# ── Page: Approval ────────────────────────────────────────────────────────────

elif page == "✅ Approval":
    st.title("✅ Human Approval")

    orch = st.session_state.get("orchestrator")
    if not orch:
        st.warning("No completed mission found. Run a mission first.")
        st.stop()

    state = orch.state

    # Show diff
    st.subheader("📄 Diff")
    from tools.git_tools import git_diff
    diff = git_diff(state.repo_path, state.workspace_path)
    if diff:
        st.code(diff[:5000], language="diff")
    else:
        st.info("No file changes detected.")

    # Criteria summary
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📊 Criteria")
        for c in state.criteria:
            icon = {"met": "✅", "unmet": "⏳", "failed": "❌"}.get(str(c.status), "⏳")
            st.markdown(f"{icon} **{c.id}**: {c.text}")
            if c.evidence:
                st.caption(f"Evidence: {c.evidence[:100]}")

    with col2:
        st.subheader("🔍 Review Issues")
        if state.review_issues:
            for issue in state.review_issues:
                sev_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
                    issue.severity, "⚪"
                )
                st.markdown(
                    f"{sev_color} [{issue.status}] **{issue.severity}** "
                    f"`{issue.file}:{issue.line}` — {issue.text}"
                )
        else:
            st.success("No review issues found.")

    # Report
    report = load_report(state.run_id)
    if report:
        with st.expander("📄 View Full Report"):
            st.markdown(report)

    st.divider()

    col_a, col_r = st.columns(2)
    with col_a:
        if st.button("✅ Approve & Apply", type="primary", use_container_width=True):
            import shutil
            ws = Path(state.workspace_path)
            orig = Path(state.repo_path)
            for src in ws.rglob("*"):
                if src.is_file():
                    rel = src.relative_to(ws)
                    dest = orig / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dest))
            orch.logger.log("human", "APPROVED", output_summary="via dashboard")
            st.success("✅ Changes applied to the original repo!")
            st.balloons()

    with col_r:
        if st.button("❌ Reject", type="secondary", use_container_width=True):
            orch.logger.log("human", "REJECTED", output_summary="via dashboard")
            st.error("❌ Changes rejected. Original repo unchanged.")


# ── Page: Past Runs ────────────────────────────────────────────────────────────

elif page == "📁 Past Runs":
    st.title("📁 Past Runs")

    logs = list_run_logs()
    if not logs:
        st.info("No past runs found. Run a mission first.")
        st.stop()

    selected_log = st.selectbox(
        "Select run",
        options=logs,
        format_func=lambda p: p.stem,
    )

    if selected_log:
        records = load_log(selected_log)
        run_id = selected_log.stem

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Events", len(records))
        with col2:
            blocked = sum(1 for r in records if r.get("event_type") == "BLOCKED")
            st.metric("Blocked commands", blocked)
        with col3:
            agents = {r.get("agent", "") for r in records}
            st.metric("Agents active", len(agents - {""}))

        # Report
        report = load_report(run_id)
        if report:
            with st.expander("📄 Report"):
                st.markdown(report)

        # Full log
        with st.expander("📋 Full Event Log"):
            for rec in records:
                agent = rec.get("agent", "?")
                event = rec.get("event_type", "")
                tool = rec.get("tool", "")
                inp = rec.get("input", "")[:50]
                out = rec.get("output_summary", "")[:80]
                blocked = event == "BLOCKED"
                icon = "🚫" if blocked else "→"
                st.markdown(
                    f"`{rec.get('time','')[-19:]}` **{agent}** {icon} **{event}**"
                    + (f" [{tool}]" if tool else "")
                    + (f" `{inp}`" if inp else "")
                )
