import { Fragment, jsxDEV } from "react/jsx-dev-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, AlertTriangle, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronDown, Command, Copy, Download, FileDiff, FileJson2, FileText, GitBranch, Layers3, LockKeyhole, MessageSquare, MoreHorizontal, Play, Plus, Search, Send, Shield, ShieldAlert, Sparkles, Terminal, Upload, X, Zap } from "lucide-react";
const colors = { planner: "#8B7CFF", developer: "#22D3EE", verifier: "#34D399", reviewer: "#FBBF24", safety: "#F87171", orchestrator: "#98A2B3", human: "#F5E6B3" };
const initials = { planner: "PL", developer: "DV", verifier: "VF", reviewer: "RV", safety: "SY", human: "HM" };
const fmt = (n) => "00:" + String(Math.floor(n / 60)).padStart(2, "0") + "." + String(Math.floor(n % 60)).padStart(2, "0");
const nl = String.fromCharCode(10);
const sample = [
  { time: 1, agent: "planner", event_type: "plan.created", tool: null, input: { request: "Add coupon support" }, output_summary: "Plan created with 3 acceptance criteria.", message_type: "PLAN_REVISED", payload: { criteria: ["Apply valid coupon to subtotal", "Round monetary values safely", "Reject negative checkout totals"] } },
  { time: 4, agent: "developer", event_type: "tool.call", tool: "read_file", input: { path: "shop/checkout.py" }, output_summary: "Mapped checkout calculation and existing tests.", message_type: null, payload: { output: "def total(subtotal, discount): return subtotal - discount" } },
  { time: 7, agent: "developer", event_type: "tool.call", tool: "edit_file", input: { approach: "Apply coupon and round to 2 decimal places" }, output_summary: "Added coupon application using round(value, 2).", message_type: null, payload: { diff: "+ total = round(subtotal - discount, 2)" } },
  { time: 10, agent: "verifier", event_type: "test.result", tool: "pytest", input: { command: "pytest -q" }, output_summary: "1 failed \u2014 binary float rounding differs from currency precision.", message_type: "TEST_FAILURE", payload: { exit_code: 1, duration: "0.42s", stdout: ["FAILED tests/test_coupon.py::test_rounding", "assert 9.989999999999998 == 9.99", "", "1 failed, 18 passed"].join(nl) } },
  { time: 13, agent: "developer", event_type: "approach.changed", tool: null, input: { before: "round(subtotal - discount, 2)", after: "Decimal quantize with ROUND_HALF_UP" }, output_summary: "Changed approach: float round() \u2192 Decimal quantize.", message_type: "PLAN_REVISED", payload: { before: "round(value, 2) uses binary floating point", after: 'Decimal(str(value)).quantize(Decimal("0.01"))' } },
  { time: 16, agent: "developer", event_type: "tool.call", tool: "edit_file", input: { path: "shop/checkout.py" }, output_summary: "Replaced float arithmetic with Decimal quantization.", message_type: null, payload: { diff: "+ Decimal quantize with ROUND_HALF_UP" } },
  { time: 19, agent: "verifier", event_type: "test.result", tool: "pytest", input: { command: "pytest -q" }, output_summary: "All 19 tests passed.", message_type: "TEST_PASS", payload: { exit_code: 0, duration: "0.38s", stdout: ["................... [100%]", "19 passed in 0.38s"].join(nl) } },
  { time: 22, agent: "verifier", event_type: "verify.finding", tool: "verify_invariant", input: { rule: "checkout total must not be negative" }, output_summary: "Found edge case: coupon can exceed subtotal, yielding a negative total.", message_type: "VERIFY_FINDING", payload: { case: "subtotal=5.00, coupon=8.00", observed: "total=-3.00", expected: "total=0.00" } },
  { time: 26, agent: "developer", event_type: "tool.call", tool: "edit_file", input: { approach: "Clamp total to zero after coupon" }, output_summary: "Added a zero floor for discounted totals.", message_type: null, payload: { diff: '+ discounted = max(Decimal("0.00"), subtotal - discount)' } },
  { time: 29, agent: "safety", event_type: "command.blocked", tool: "curl", input: { command: "curl https://example.com" }, output_summary: "Blocked command: curl is not on the allow-list.", message_type: "BLOCKED", payload: { reason: "curl is not on the allow-list", policy: "Network access is disabled in this sandbox." } },
  { time: 33, agent: "reviewer", event_type: "review.issue", tool: "review_diff", input: { path: "config.py", line: 12 }, output_summary: "Hardcoded API key found in config.py.", message_type: "REVIEW_ISSUE", payload: { line: 12, code: 'PAYMENTS_API_KEY = "sk_test_..."', comment: "Read secrets from the environment." } },
  { time: 37, agent: "developer", event_type: "tool.call", tool: "edit_file", input: { path: "config.py" }, output_summary: "Removed hardcoded key; reads from environment.", message_type: null, payload: { diff: ['- PAYMENTS_API_KEY = "sk_test_..."', '+ PAYMENTS_API_KEY = os.getenv("PAYMENTS_API_KEY", "")'].join(nl) } },
  { time: 41, agent: "verifier", event_type: "test.result", tool: "pytest", input: { command: "pytest -q" }, output_summary: "All 20 tests passed, including coupon bounds and precision.", message_type: "TEST_PASS", payload: { exit_code: 0, duration: "0.41s", stdout: [".................... [100%]", "20 passed in 0.41s"].join(nl) } },
  { time: 44, agent: "reviewer", event_type: "review.approved", tool: "review_diff", input: { files: ["shop/checkout.py", "config.py"] }, output_summary: "Review complete. No unresolved issues.", message_type: null, payload: { result: "approved", open_issues: 0 } },
  { time: 48, agent: "orchestrator", event_type: "report.ready", tool: null, input: { retries: 1 }, output_summary: "Evidence report ready. Awaiting human approval.", message_type: null, payload: { verified: ["Coupon discount applied", "Decimal precision verified", "Negative total prevented", "20 tests passed"], assumptions: ["Live payment provider integration not exercised"] } }
];
const agents = ["planner", "developer", "verifier", "reviewer"];
function Avatar({ a, size = 27 }) {
  return /* @__PURE__ */ jsxDEV("span", { className: "avatar", style: { "--agent": colors[a], width: size, height: size }, children: a === "safety" ? /* @__PURE__ */ jsxDEV(Shield, { size: 14 }, void 0, false, {
    fileName: "<stdin>",
    lineNumber: 25,
    columnNumber: 175
  }, this) : initials[a] || "OR" }, void 0, false, {
    fileName: "<stdin>",
    lineNumber: 25,
    columnNumber: 60
  }, this);
}
function Badge({ children, tone = "muted" }) {
  return /* @__PURE__ */ jsxDEV("span", { className: "badge " + tone, children }, void 0, false, {
    fileName: "<stdin>",
    lineNumber: 26,
    columnNumber: 88
  }, this);
}
function App() {
  const [tab, setTab] = useState("Live Run"), [events, setEvents] = useState(sample), [sampleMode, setSampleMode] = useState(true), [mission, setMission] = useState("Add coupon support to mini_shop checkout"), [screen, setScreen] = useState(false), [filter, setFilter] = useState(null), [expanded, setExpanded] = useState(3), [playing, setPlaying] = useState(false), [cursor, setCursor] = useState(sample.length), [speed, setSpeed] = useState(1), [left, setLeft] = useState(true), [right, setRight] = useState(true), [palette, setPalette] = useState(false), [modal, setModal] = useState(false), [approved, setApproved] = useState(false), [reject, setReject] = useState(false), [reason, setReason] = useState(""), [toast, setToast] = useState(""), [search, setSearch] = useState(""), [request, setRequest] = useState(""), [repo, setRepo] = useState("mini_shop"), [attempts, setAttempts] = useState(["round(value, 2) \u2192 float precision mismatch", "Decimal quantize \u2192 negative total edge case"]);
  const input = useRef(null);
  useEffect(() => {
    const fn = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((v) => !v);
      }
      if (e.key === "Escape") {
        setPalette(false);
        setModal(false);
      }
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3e3);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("devpilot-run");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length) {
          setEvents(parsed);
          setCursor(parsed.length);
          setSampleMode(false);
          setMission("Restored uploaded run");
        }
      }
    } catch {
    }
  }, []);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setCursor((c) => {
      if (c >= events.length) {
        setPlaying(false);
        return c;
      }
      return c + 1;
    }), 1200 / speed);
    return () => clearInterval(t);
  }, [playing, speed, events.length]);
  const upload = (file) => {
    if (!file) return;
    const r = new FileReader();
    r.onload = () => {
      try {
        const parsed = String(r.result).split(/\r?\n/).filter(Boolean).map((x) => JSON.parse(x)).sort((a, b) => a.time - b.time);
        if (!parsed.length) throw Error();
        setEvents(parsed);
        setMission(file.name.replace(/\.jsonl$/i, "").replace(/[_-]/g, " "));
        setSampleMode(false);
        setCursor(0);
        setPlaying(false);
        setFilter(null);
        setScreen(false);
        localStorage.setItem("devpilot-run", JSON.stringify(parsed));
        setToast("Run log loaded \xB7 sample data removed");
      } catch {
        setToast("Could not read JSONL. Check the event format.");
      }
    };
    r.readAsText(file);
  };
  const loadSample = () => {
    setEvents(sample);
    setSampleMode(true);
    setCursor(sample.length);
    setPlaying(false);
    setMission("Add coupon support to mini_shop checkout");
    setScreen(false);
    setTab("Live Run");
    setToast("Sample run loaded");
  };
  const start = () => {
    if (!request.trim()) {
      setToast("Describe the change you want to make");
      return;
    }
    setMission(request);
    setEvents([{ time: 0, agent: "planner", event_type: "plan.created", tool: null, input: { request, repo }, output_summary: "Mission queued. Planning has started.", message_type: null, payload: { criteria: ["Clarify desired behavior", "Implement change", "Verify with tests"] } }]);
    setCursor(1);
    setSampleMode(false);
    setScreen(false);
    setToast("Mission created \xB7 awaiting connected agent runtime");
  };
  const visible = useMemo(() => events.slice(0, cursor).filter((e) => !filter || e.agent === filter), [events, cursor, filter]);
  const exportReport = () => {
    const text = ["# DevPilot Evidence Report", "", "## VERIFIED", "- pytest -q \u2014 20 passed", "- Decimal currency precision verified", "- Negative checkout totals prevented", "", "## NOT VERIFIED / assumptions", "- Live payment provider integration not exercised", "", "## Changed files", "- shop/checkout.py", "- config.py", "", "Retries used: 1/3"].join(String.fromCharCode(10));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    a.download = "devpilot-report.md";
    a.click();
    URL.revokeObjectURL(a.href);
    setToast("Markdown report exported");
  };
  const commands = [["Live Run", () => setTab("Live Run")], ["Terminal", () => setTab("Terminal")], ["Diff", () => setTab("Diff")], ["Report", () => setTab("Report")], ["Load sample run", loadSample], ["Load run log\u2026", () => input.current?.click()], ["Toggle plan panel", () => setRight((v) => !v)], ["Clear agent filter", () => setFilter(null)]];
  return /* @__PURE__ */ jsxDEV("div", { className: "app", children: [
    /* @__PURE__ */ jsxDEV("header", { className: "topbar", children: [
      /* @__PURE__ */ jsxDEV("div", { className: "brand", children: [
        /* @__PURE__ */ jsxDEV("span", { className: "logo", children: [
          "D",
          /* @__PURE__ */ jsxDEV("span", { children: "\xB7" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 32,
            columnNumber: 103
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 79
        }, this),
        /* @__PURE__ */ jsxDEV("b", { children: "DevPilot" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 124
        }, this),
        /* @__PURE__ */ jsxDEV("small", { children: "MISSION CONTROL" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 139
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 32,
        columnNumber: 56
      }, this),
      /* @__PURE__ */ jsxDEV("i", { className: "divider" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 32,
        columnNumber: 175
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "mission-title", onClick: () => setScreen(!screen), children: [
        screen ? "New mission" : mission,
        /* @__PURE__ */ jsxDEV(ChevronDown, { size: 14 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 296
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 32,
        columnNumber: 199
      }, this),
      /* @__PURE__ */ jsxDEV("div", { className: "status-pill", children: [
        /* @__PURE__ */ jsxDEV("i", {}, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 358
        }, this),
        " ",
        approved ? "Done" : events.some((e) => e.event_type === "escalated") ? "Escalated" : events.some((e) => e.event_type === "clarification.needed") ? "Clarification needed" : cursor >= events.length ? "Awaiting approval" : "Building"
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 32,
        columnNumber: 329
      }, this),
      /* @__PURE__ */ jsxDEV("div", { className: "metrics", children: [
        /* @__PURE__ */ jsxDEV("span", { children: [
          "RETRIES ",
          /* @__PURE__ */ jsxDEV("b", { children: [
            "1",
            /* @__PURE__ */ jsxDEV("em", { children: "/3" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 32,
              columnNumber: 614
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 32,
            columnNumber: 610
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 596
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          "STEPS ",
          /* @__PURE__ */ jsxDEV("b", { children: Math.min(cursor, events.length) }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 32,
            columnNumber: 648
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 636
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          "TOOL CALLS ",
          /* @__PURE__ */ jsxDEV("b", { children: events.filter((e) => e.tool).length }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 32,
            columnNumber: 711
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 694
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          "BLOCKED ",
          /* @__PURE__ */ jsxDEV("b", { className: "red", children: events.filter((e) => e.event_type === "command.blocked").length }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 32,
            columnNumber: 772
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 758
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 32,
        columnNumber: 571
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "command-btn", onClick: () => setPalette(true), children: [
        /* @__PURE__ */ jsxDEV(Command, { size: 13 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 32,
          columnNumber: 930
        }, this),
        " \u2318 K"
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 32,
        columnNumber: 867
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "icon-btn mobile-panel", onClick: () => setRight(!right), children: /* @__PURE__ */ jsxDEV(Layers3, { size: 15 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 32,
        columnNumber: 1036
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 32,
        columnNumber: 963
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 32,
      columnNumber: 29
    }, this),
    screen ? /* @__PURE__ */ jsxDEV("main", { className: "start", children: [
      /* @__PURE__ */ jsxDEV("button", { className: "back", onClick: () => setScreen(false), children: [
        /* @__PURE__ */ jsxDEV(ArrowLeft, { size: 14 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 89
        }, this),
        " Back to mission"
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 33,
        columnNumber: 33
      }, this),
      /* @__PURE__ */ jsxDEV("section", { className: "start-content", children: [
        /* @__PURE__ */ jsxDEV("span", { className: "eyebrow", children: [
          /* @__PURE__ */ jsxDEV(Sparkles, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 197
          }, this),
          " NEW MISSION"
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 171
        }, this),
        /* @__PURE__ */ jsxDEV("h1", { children: [
          "What should the",
          /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 256
          }, this),
          /* @__PURE__ */ jsxDEV("span", { children: "guild build?" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 261
          }, this),
          /* @__PURE__ */ jsxDEV("i", { className: "cursor" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 286
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 237
        }, this),
        /* @__PURE__ */ jsxDEV("div", { className: "request-box", children: [
          /* @__PURE__ */ jsxDEV("textarea", { autoFocus: true, placeholder: "Describe a change, fix, or feature\u2026", value: request, onChange: (e) => setRequest(e.target.value), onKeyDown: (e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) start();
          } }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 343
          }, this),
          /* @__PURE__ */ jsxDEV("div", { className: "request-foot", children: [
            /* @__PURE__ */ jsxDEV("label", { children: [
              "REPOSITORY ",
              /* @__PURE__ */ jsxDEV("select", { value: repo, onChange: (e) => setRepo(e.target.value), children: ["mini_shop", "bugfix_repo", "failing_test_repo", "security_repo", "stuck_repo", "notools_repo", "revision_repo"].map((x) => /* @__PURE__ */ jsxDEV("option", { children: x }, x, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 762
              }, this)) }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 587
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 569
            }, this),
            /* @__PURE__ */ jsxDEV("button", { className: "gold-button", onClick: start, children: [
              "Start mission ",
              /* @__PURE__ */ jsxDEV(ArrowRight, { size: 15 }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 871
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 809
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 539
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 314
        }, this),
        /* @__PURE__ */ jsxDEV("div", { className: "examples", children: [
          /* @__PURE__ */ jsxDEV("small", { children: "TRY" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 941
          }, this),
          ["Add coupon support to checkout", "Fix the failing cart test", "Harden config secrets"].map((x) => /* @__PURE__ */ jsxDEV("button", { onClick: () => setRequest(x), children: x }, x, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1054
          }, this))
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 915
        }, this),
        /* @__PURE__ */ jsxDEV("div", { className: "rule-chips", children: [
          /* @__PURE__ */ jsxDEV(Badge, { children: [
            "MAX RETRIES ",
            /* @__PURE__ */ jsxDEV("b", { children: "3" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 1165
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1146
          }, this),
          /* @__PURE__ */ jsxDEV(Badge, { children: "SANDBOXED COPY" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1181
          }, this),
          /* @__PURE__ */ jsxDEV(Badge, { children: "HUMAN APPROVAL REQUIRED" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1210
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 1118
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 33,
        columnNumber: 136
      }, this),
      /* @__PURE__ */ jsxDEV("div", { className: "start-foot", children: [
        /* @__PURE__ */ jsxDEV("span", { children: "DEVpilot / SANDBOX SESSION" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 1292
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: "NO CHANGES APPLY WITHOUT APPROVAL" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 1331
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 33,
        columnNumber: 1264
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 33,
      columnNumber: 9
    }, this) : /* @__PURE__ */ jsxDEV(Fragment, { children: [
      /* @__PURE__ */ jsxDEV("div", { className: "workspace", children: [
        left && /* @__PURE__ */ jsxDEV("aside", { className: "left", children: [
          /* @__PURE__ */ jsxDEV("div", { className: "side-title", children: [
            "MISSIONS",
            /* @__PURE__ */ jsxDEV("button", { className: "icon-btn", onClick: () => {
              setScreen(true);
              setRequest("");
            }, children: /* @__PURE__ */ jsxDEV(Plus, { size: 15 }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 1563
            }, this) }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 1487
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1451
          }, this),
          /* @__PURE__ */ jsxDEV("button", { className: "mission-row", children: [
            /* @__PURE__ */ jsxDEV("i", { className: "mission-dot" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 1627
            }, this),
            /* @__PURE__ */ jsxDEV("span", { children: [
              /* @__PURE__ */ jsxDEV("b", { children: "Coupon checkout" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 1661
              }, this),
              /* @__PURE__ */ jsxDEV("small", { children: "mini_shop \xB7 just now" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 1683
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 1655
            }, this),
            /* @__PURE__ */ jsxDEV(MoreHorizontal, { size: 14 }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 1725
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1595
          }, this),
          /* @__PURE__ */ jsxDEV("button", { className: "new-mission", onClick: () => {
            setScreen(true);
            setRequest("");
          }, children: [
            /* @__PURE__ */ jsxDEV(Plus, { size: 14 }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 1840
            }, this),
            " New mission"
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1761
          }, this),
          /* @__PURE__ */ jsxDEV("div", { className: "side-title agent-head", children: [
            "AGENTS ",
            /* @__PURE__ */ jsxDEV("span", { children: "4 ACTIVE" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 1924
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1878
          }, this),
          agents.map((a, i) => /* @__PURE__ */ jsxDEV("button", { className: "agent-row " + (filter === a ? "chosen" : ""), onClick: () => setFilter(filter === a ? null : a), children: [
            /* @__PURE__ */ jsxDEV(Avatar, { a, size: 25 }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 2079
            }, this),
            /* @__PURE__ */ jsxDEV("span", { children: [
              /* @__PURE__ */ jsxDEV("b", { children: a }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2110
              }, this),
              /* @__PURE__ */ jsxDEV("small", { children: ["thinking", "using tool", "verifying", "reviewing"][i] }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2120
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 2104
            }, this),
            /* @__PURE__ */ jsxDEV(Spark, { i, color: colors[a] }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 2196
            }, this)
          ] }, a, true, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 1970
          }, this)),
          /* @__PURE__ */ jsxDEV("div", { className: "side-bottom", children: [
            /* @__PURE__ */ jsxDEV("div", { className: "side-title", children: [
              "SESSION ",
              /* @__PURE__ */ jsxDEV("i", { className: "green-dot" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2304
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 2268
            }, this),
            /* @__PURE__ */ jsxDEV("button", { className: "load-run", onClick: () => input.current?.click(), children: [
              /* @__PURE__ */ jsxDEV(Upload, { size: 14 }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2402
              }, this),
              " Load run log ",
              /* @__PURE__ */ jsxDEV("small", { children: "\u2318O" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2435
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 2336
            }, this),
            /* @__PURE__ */ jsxDEV("div", { className: "toggle-line", children: [
              /* @__PURE__ */ jsxDEV("span", { children: "DATA SOURCE" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2490
              }, this),
              /* @__PURE__ */ jsxDEV("button", { className: sampleMode ? "active" : "", onClick: loadSample, children: "Demo" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2514
              }, this),
              /* @__PURE__ */ jsxDEV("button", { className: !sampleMode ? "active" : "", onClick: () => {
                setSampleMode(false);
                setToast("Real data mode \xB7 load a JSONL run");
              }, children: "Real" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2591
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 2461
            }, this),
            /* @__PURE__ */ jsxDEV("small", { className: "secure", children: [
              /* @__PURE__ */ jsxDEV(Shield, { size: 11 }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 33,
                columnNumber: 2763
              }, this),
              " SANDBOXED ENVIRONMENT"
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 2737
            }, this),
            /* @__PURE__ */ jsxDEV("small", { className: "version", children: "v0.8.4 \xB7 session 8f2a1c" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 33,
              columnNumber: 2812
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 33,
            columnNumber: 2239
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 33,
          columnNumber: 1427
        }, this),
        /* @__PURE__ */ jsxDEV("main", { className: "center", children: [
          /* @__PURE__ */ jsxDEV("div", { className: "center-head", children: [
            /* @__PURE__ */ jsxDEV("div", { className: "tabs", children: ["Live Run", "Terminal", "Diff", "Report"].map((t, i) => /* @__PURE__ */ jsxDEV("button", { className: tab === t ? "active" : "", onClick: () => setTab(t), children: [
              [/* @__PURE__ */ jsxDEV(Activity, {}, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 214
              }, this), /* @__PURE__ */ jsxDEV(Terminal, {}, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 226
              }, this), /* @__PURE__ */ jsxDEV(FileDiff, {}, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 238
              }, this), /* @__PURE__ */ jsxDEV(FileText, {}, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 250
              }, this)][i],
              t,
              t === "Terminal" && /* @__PURE__ */ jsxDEV("small", { children: "4" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 286
              }, this)
            ] }, t, true, {
              fileName: "<stdin>",
              lineNumber: 34,
              columnNumber: 140
            }, this)) }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 34,
              columnNumber: 55
            }, this),
            /* @__PURE__ */ jsxDEV("div", { className: "center-meta", children: [
              sampleMode && /* @__PURE__ */ jsxDEV(Badge, { tone: "sample", children: "SAMPLE DATA" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 362
              }, this),
              /* @__PURE__ */ jsxDEV("code", { children: "RUN_8F2A1C" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 403
              }, this),
              /* @__PURE__ */ jsxDEV("button", { className: "icon-btn", onClick: () => setLeft(!left), children: /* @__PURE__ */ jsxDEV(Layers3, { size: 14 }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 484
              }, this) }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 34,
                columnNumber: 426
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 34,
              columnNumber: 320
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 34,
            columnNumber: 26
          }, this),
          /* @__PURE__ */ jsxDEV(AnimatePresence, { mode: "wait", children: /* @__PURE__ */ jsxDEV(motion.div, { className: "view", initial: { opacity: 0, y: 4 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0 }, transition: { duration: 0.18 }, children: tab === "Live Run" ? /* @__PURE__ */ jsxDEV(Live, { events: visible, all: events, filter, setFilter, expanded, setExpanded, sampleMode, setModal, approved, playing, setPlaying, cursor, setCursor, speed, setSpeed }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 34,
            columnNumber: 710
          }, this) : tab === "Terminal" ? /* @__PURE__ */ jsxDEV(TerminalView, { events: events.slice(0, cursor), search, setSearch, sampleMode, toast: setToast }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 34,
            columnNumber: 1027
          }, this) : tab === "Diff" ? /* @__PURE__ */ jsxDEV(DiffView, { sampleMode }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 34,
            columnNumber: 1167
          }, this) : /* @__PURE__ */ jsxDEV(ReportView, { sampleMode, exportReport }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 34,
            columnNumber: 1203
          }, this) }, tab, false, {
            fileName: "<stdin>",
            lineNumber: 34,
            columnNumber: 554
          }, this) }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 34,
            columnNumber: 525
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 34,
          columnNumber: 1
        }, this),
        right && /* @__PURE__ */ jsxDEV("aside", { className: "right", children: /* @__PURE__ */ jsxDEV(RightPanel, { events: events.slice(0, cursor), attempts, setAttempts, sampleMode }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 34,
          columnNumber: 1340
        }, this) }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 34,
          columnNumber: 1315
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 33,
        columnNumber: 1393
      }, this),
      /* @__PURE__ */ jsxDEV("nav", { className: "mobile-nav", children: [["Run", Activity], ["Terminal", Terminal], ["Diff", FileDiff], ["Report", FileText], ["Plan", CheckCircle2]].map(([n, I]) => /* @__PURE__ */ jsxDEV("button", { onClick: () => n === "Plan" ? setRight(true) : setTab(n === "Run" ? "Live Run" : n), children: [
        /* @__PURE__ */ jsxDEV(I, { size: 17 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 34,
          columnNumber: 1704
        }, this),
        n
      ] }, n, true, {
        fileName: "<stdin>",
        lineNumber: 34,
        columnNumber: 1617
      }, this)) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 34,
        columnNumber: 1470
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 33,
      columnNumber: 1391
    }, this),
    /* @__PURE__ */ jsxDEV("input", { ref: input, type: "file", accept: ".jsonl,application/json,text/plain", hidden: true, onChange: (e) => upload(e.target.files?.[0]) }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 1
    }, this),
    /* @__PURE__ */ jsxDEV(AnimatePresence, { children: modal && /* @__PURE__ */ jsxDEV(Approval, { onClose: () => setModal(false), approve: () => {
      setApproved(true);
      setModal(false);
      setToast("Mission approved \xB7 ready to apply");
    }, reject, setReject, reason, setReason, sampleMode }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 151
    }, this) }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 126
    }, this),
    approved && /* @__PURE__ */ jsxDEV(motion.div, { className: "stamp", initial: { scale: 2.5, rotate: -15, opacity: 0 }, animate: { scale: 1, rotate: -8, opacity: 1 }, transition: { type: "spring", stiffness: 300, damping: 14 }, children: "APPROVED" }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 418
    }, this),
    /* @__PURE__ */ jsxDEV(AnimatePresence, { children: palette && /* @__PURE__ */ jsxDEV(Palette, { commands, close: () => setPalette(false) }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 634
    }, this) }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 607
    }, this),
    /* @__PURE__ */ jsxDEV(AnimatePresence, { children: toast && /* @__PURE__ */ jsxDEV(motion.div, { className: "toast", initial: { y: 14, opacity: 0 }, animate: { y: 0, opacity: 1 }, exit: { opacity: 0 }, children: [
      /* @__PURE__ */ jsxDEV("i", {}, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 35,
        columnNumber: 840
      }, this),
      toast,
      /* @__PURE__ */ jsxDEV("button", { onClick: () => setToast(""), children: /* @__PURE__ */ jsxDEV(X, { size: 13 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 35,
        columnNumber: 886
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 35,
        columnNumber: 851
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 738
    }, this) }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 713
    }, this),
    /* @__PURE__ */ jsxDEV("span", { className: "sr", "aria-live": "polite", children: [
      visible.length,
      " run events"
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 35,
      columnNumber: 941
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 32,
    columnNumber: 8
  }, this);
}
function Spark({ i, color }) {
  const points = ["1,13 8,9 14,12 20,5 27,8 34,3 41,8 50,2", "1,12 8,14 14,5 21,10 28,4 35,9 42,3 50,6", "1,11 8,7 15,9 22,3 29,5 36,2 43,6 50,1", "1,14 8,8 15,12 21,6 28,9 35,3 42,5 50,2"];
  return /* @__PURE__ */ jsxDEV("svg", { className: "spark", viewBox: "0 0 52 18", children: /* @__PURE__ */ jsxDEV("polyline", { points: points[i], fill: "none", stroke: color, strokeWidth: "1.5", strokeLinecap: "round" }, void 0, false, {
    fileName: "<stdin>",
    lineNumber: 36,
    columnNumber: 284
  }, this) }, void 0, false, {
    fileName: "<stdin>",
    lineNumber: 36,
    columnNumber: 241
  }, this);
}
function Live({ events, all, filter, setFilter, expanded, setExpanded, sampleMode, setModal, approved, playing, setPlaying, cursor, setCursor, speed, setSpeed }) {
  const loop = events.some((e) => e.message_type === "TEST_FAILURE");
  return /* @__PURE__ */ jsxDEV("div", { className: "live", children: [
    /* @__PURE__ */ jsxDEV("div", { className: "section-title", children: [
      /* @__PURE__ */ jsxDEV("div", { children: [
        /* @__PURE__ */ jsxDEV("h2", { children: "Agent constellation" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 575
        }, this),
        /* @__PURE__ */ jsxDEV("p", { children: "Messages moving through the mission" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 603
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 570
      }, this),
      /* @__PURE__ */ jsxDEV("span", { className: "legend", children: [
        /* @__PURE__ */ jsxDEV("i", {}, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 676
        }, this),
        " LIVE"
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 651
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 37,
      columnNumber: 539
    }, this),
    /* @__PURE__ */ jsxDEV(Constellation, { filter, setFilter }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 37,
      columnNumber: 698
    }, this),
    events.some((e) => e.event_type === "escalated") && /* @__PURE__ */ jsxDEV("div", { className: "escalated-card", children: [
      /* @__PURE__ */ jsxDEV(ShieldAlert, { size: 17 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 829
      }, this),
      /* @__PURE__ */ jsxDEV("div", { children: [
        /* @__PURE__ */ jsxDEV("b", { children: "Escalated to human" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 858
        }, this),
        /* @__PURE__ */ jsxDEV("small", { children: events.find((e) => e.event_type === "escalated")?.output_summary }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 883
        }, this),
        /* @__PURE__ */ jsxDEV("code", { children: "Evidence collected \xB7 attempts recorded \xB7 sandbox unchanged" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 958
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 853
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 37,
      columnNumber: 797
    }, this),
    events.some((e) => e.event_type === "clarification.needed") && /* @__PURE__ */ jsxDEV(ClarifyCard, { question: events.find((e) => e.event_type === "clarification.needed")?.output_summary || "Which behavior should the agent implement?" }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 37,
      columnNumber: 1098
    }, this),
    loop && /* @__PURE__ */ jsxDEV(motion.div, { className: "loop-card", initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, children: [
      /* @__PURE__ */ jsxDEV("div", { className: "loop-symbol", children: /* @__PURE__ */ jsxDEV(Activity, { size: 18 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 1362
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 1333
      }, this),
      /* @__PURE__ */ jsxDEV("div", { className: "loop-body", children: [
        /* @__PURE__ */ jsxDEV("div", { children: [
          /* @__PURE__ */ jsxDEV("b", { children: [
            "Test failed ",
            /* @__PURE__ */ jsxDEV("span", { children: "\u2192" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 37,
              columnNumber: 1436
            }, this),
            " Developer changed approach"
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 1421
          }, this),
          /* @__PURE__ */ jsxDEV(Badge, { tone: "loop", children: "LOOP 2 OF 3" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 1481
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 1416
        }, this),
        /* @__PURE__ */ jsxDEV("div", { className: "approaches", children: [
          /* @__PURE__ */ jsxDEV("section", { children: [
            /* @__PURE__ */ jsxDEV("label", { children: "BEFORE" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 37,
              columnNumber: 1562
            }, this),
            /* @__PURE__ */ jsxDEV("code", { children: "round(value, 2)" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 37,
              columnNumber: 1583
            }, this),
            /* @__PURE__ */ jsxDEV("small", { children: "Binary float precision drift" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 37,
              columnNumber: 1611
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 1553
          }, this),
          /* @__PURE__ */ jsxDEV(ArrowRight, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 1664
          }, this),
          /* @__PURE__ */ jsxDEV("section", { children: [
            /* @__PURE__ */ jsxDEV("label", { children: "AFTER" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 37,
              columnNumber: 1696
            }, this),
            /* @__PURE__ */ jsxDEV("code", { children: "Decimal quantize" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 37,
              columnNumber: 1716
            }, this),
            /* @__PURE__ */ jsxDEV("small", { children: "Deterministic currency math" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 37,
              columnNumber: 1745
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 1687
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 1525
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 1389
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 37,
      columnNumber: 1247
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "timeline-heading", children: [
      /* @__PURE__ */ jsxDEV("div", { children: [
        /* @__PURE__ */ jsxDEV("b", { children: "Run timeline" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 1862
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          events.length,
          " events"
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 1881
        }, this),
        filter && /* @__PURE__ */ jsxDEV("button", { className: "filter-chip", onClick: () => setFilter(null), children: [
          filter,
          /* @__PURE__ */ jsxDEV(X, { size: 10 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 1995
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 1925
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 1857
      }, this),
      /* @__PURE__ */ jsxDEV("div", { className: "replay-bar", children: [
        /* @__PURE__ */ jsxDEV("button", { "aria-label": playing ? "Pause replay" : "Play replay", onClick: () => {
          if (cursor >= all.length) setCursor(0);
          setPlaying(!playing);
        }, children: playing ? "\u2161" : /* @__PURE__ */ jsxDEV(Play, { size: 11 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 2196
        }, this) }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 2053
        }, this),
        /* @__PURE__ */ jsxDEV("input", { "aria-label": "Replay scrubber", type: "range", min: "0", max: all.length, value: Math.min(cursor, all.length), onChange: (e) => {
          setCursor(Number(e.target.value));
          setPlaying(false);
        } }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 2223
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          String(Math.min(cursor, all.length)).padStart(2, "0"),
          "/",
          String(all.length).padStart(2, "0")
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 2402
        }, this),
        /* @__PURE__ */ jsxDEV("select", { "aria-label": "Replay speed", value: speed, onChange: (e) => setSpeed(Number(e.target.value)), children: [
          /* @__PURE__ */ jsxDEV("option", { value: "1", children: "1\xD7" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 2600
          }, this),
          /* @__PURE__ */ jsxDEV("option", { value: "2", children: "2\xD7" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 2629
          }, this),
          /* @__PURE__ */ jsxDEV("option", { value: "5", children: "5\xD7" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 2658
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 2505
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 2025
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 37,
      columnNumber: 1823
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "timeline", children: [
      events.map((e, i) => /* @__PURE__ */ jsxDEV(EventRow, { e, i, expanded: expanded === i, toggle: () => setExpanded(expanded === i ? null : i), sampleMode }, i, false, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 2753
      }, this)),
      !events.length && /* @__PURE__ */ jsxDEV("div", { className: "empty", children: [
        /* @__PURE__ */ jsxDEV(Activity, { size: 23 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 2920
        }, this),
        /* @__PURE__ */ jsxDEV("b", { children: "No events yet" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 2941
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: "Load a run log or start a mission." }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 2961
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 2897
      }, this),
      events.length === all.length && /* @__PURE__ */ jsxDEV("div", { className: "approval-callout", children: [
        /* @__PURE__ */ jsxDEV(CheckCircle2, { size: 20 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 3078
        }, this),
        /* @__PURE__ */ jsxDEV("div", { children: [
          /* @__PURE__ */ jsxDEV("b", { children: approved ? "Mission approved" : "Mission ready for approval" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 3108
          }, this),
          /* @__PURE__ */ jsxDEV("small", { children: approved ? "Cleared to apply." : "20 tests passed \xB7 3 criteria met \xB7 0 open issues" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 3173
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 3103
        }, this),
        !approved && /* @__PURE__ */ jsxDEV("button", { onClick: setModal, children: [
          "Review & approve ",
          /* @__PURE__ */ jsxDEV(ArrowRight, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 37,
            columnNumber: 3331
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 37,
          columnNumber: 3287
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 37,
        columnNumber: 3044
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 37,
      columnNumber: 2708
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 37,
    columnNumber: 517
  }, this);
}
function Constellation({ filter, setFilter }) {
  const nodes = [["planner", "Planner", "np"], ["developer", "Developer", "nd"], ["verifier", "Verifier", "nv"], ["reviewer", "Reviewer", "nr"], ["human", "Human", "nh"], ["safety", "Safety", "ns"]];
  return /* @__PURE__ */ jsxDEV("div", { className: "constellation", children: [
    /* @__PURE__ */ jsxDEV("div", { className: "const-grid" }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 38,
      columnNumber: 335
    }, this),
    /* @__PURE__ */ jsxDEV("svg", { viewBox: "0 0 700 230", preserveAspectRatio: "none", children: [
      /* @__PURE__ */ jsxDEV("path", { d: "M150 72 C210 22 250 38 310 94" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 418
      }, this),
      /* @__PURE__ */ jsxDEV("path", { d: "M330 101 C390 52 438 54 496 80" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 459
      }, this),
      /* @__PURE__ */ jsxDEV("path", { d: "M340 120 C390 174 438 171 496 133" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 501
      }, this),
      /* @__PURE__ */ jsxDEV("path", { d: "M505 125 C560 136 586 170 620 187" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 546
      }, this),
      /* @__PURE__ */ jsxDEV("path", { d: "M286 122 C226 163 206 182 157 190" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 591
      }, this),
      /* @__PURE__ */ jsxDEV("circle", { r: "3", children: /* @__PURE__ */ jsxDEV("animateMotion", { dur: "3s", repeatCount: "indefinite", path: "M150 72 C210 22 250 38 310 94" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 650
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 636
      }, this),
      /* @__PURE__ */ jsxDEV("circle", { r: "3", children: /* @__PURE__ */ jsxDEV("animateMotion", { dur: "3.8s", repeatCount: "indefinite", path: "M330 101 C390 52 438 54 496 80" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 760
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 746
      }, this),
      /* @__PURE__ */ jsxDEV("circle", { r: "3", children: /* @__PURE__ */ jsxDEV("animateMotion", { dur: "3.4s", repeatCount: "indefinite", path: "M340 120 C390 174 438 171 496 133" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 873
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 859
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 38,
      columnNumber: 364
    }, this),
    nodes.map(([a, n, c]) => /* @__PURE__ */ jsxDEV("button", { className: "node " + c + (filter === a ? " selected" : ""), onClick: () => setFilter(filter === a ? null : a), children: [
      /* @__PURE__ */ jsxDEV("span", { className: "node-core", children: /* @__PURE__ */ jsxDEV(Avatar, { a, size: 31 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 1140
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 1112
      }, this),
      /* @__PURE__ */ jsxDEV("b", { children: n }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 1172
      }, this),
      /* @__PURE__ */ jsxDEV("small", { children: a === "human" ? "waiting" : a === "safety" ? "watching" : a === "developer" ? "working" : a === "verifier" ? "testing" : "ready" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 1182
      }, this)
    ] }, a, true, {
      fileName: "<stdin>",
      lineNumber: 38,
      columnNumber: 1003
    }, this)),
    /* @__PURE__ */ jsxDEV("span", { className: "msg-tag tag-one", children: "PLAN_REVISED" }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 38,
      columnNumber: 1314
    }, this),
    /* @__PURE__ */ jsxDEV("span", { className: "msg-tag tag-two", children: "TEST_FAILURE" }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 38,
      columnNumber: 1367
    }, this),
    /* @__PURE__ */ jsxDEV("span", { className: "msg-tag tag-three", children: "REVIEW_ISSUE" }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 38,
      columnNumber: 1420
    }, this),
    /* @__PURE__ */ jsxDEV("span", { className: "orbit-label", children: [
      /* @__PURE__ */ jsxDEV(Activity, { size: 11 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 38,
        columnNumber: 1505
      }, this),
      " LOOP 2/3"
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 38,
      columnNumber: 1475
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 38,
    columnNumber: 304
  }, this);
}
function EventRow({ e, i, expanded, toggle, sampleMode }) {
  const fail = e.event_type === "test.result" && e.payload?.exit_code !== 0, blocked = e.event_type === "command.blocked", pass = e.event_type === "test.result" && e.payload?.exit_code === 0;
  return /* @__PURE__ */ jsxDEV(motion.div, { className: "event " + (blocked ? "blocked" : ""), initial: { opacity: 0, x: -8 }, animate: { opacity: 1, x: 0 }, transition: { duration: 0.18, delay: Math.min(i * 0.012, 0.16) }, children: [
    /* @__PURE__ */ jsxDEV("div", { className: "event-rail", children: [
      /* @__PURE__ */ jsxDEV(Avatar, { a: e.agent, size: 27 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 39,
        columnNumber: 486
      }, this),
      /* @__PURE__ */ jsxDEV("i", {}, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 39,
        columnNumber: 517
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 39,
      columnNumber: 458
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "event-content", children: [
      /* @__PURE__ */ jsxDEV("button", { className: "event-top", onClick: toggle, children: [
        /* @__PURE__ */ jsxDEV("time", { children: fmt(e.time) }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 605
        }, this),
        /* @__PURE__ */ jsxDEV("b", { style: { color: colors[e.agent] }, children: e.agent }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 631
        }, this),
        e.tool && /* @__PURE__ */ jsxDEV("code", { className: "tool-chip", children: e.tool }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 688
        }, this),
        /* @__PURE__ */ jsxDEV("span", { className: "event-summary", children: e.output_summary }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 732
        }, this),
        e.message_type && /* @__PURE__ */ jsxDEV(Badge, { tone: fail ? "fail" : blocked ? "blocked" : pass ? "success" : "signal", children: e.message_type }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 806
        }, this),
        sampleMode && /* @__PURE__ */ jsxDEV("small", { className: "sample-mark", children: "SAMPLE" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 912
        }, this),
        /* @__PURE__ */ jsxDEV(ChevronDown, { size: 12, className: expanded ? "" : "turn" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 958
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 39,
        columnNumber: 558
      }, this),
      expanded && /* @__PURE__ */ jsxDEV(motion.div, { className: "event-details", initial: { height: 0, opacity: 0 }, animate: { height: "auto", opacity: 1 }, children: [
        /* @__PURE__ */ jsxDEV("div", { className: "detail-label", children: [
          "INPUT ",
          /* @__PURE__ */ jsxDEV("code", { children: e.event_type }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 39,
            columnNumber: 1174
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 1138
        }, this),
        /* @__PURE__ */ jsxDEV("pre", { children: JSON.stringify(e.input, null, 2) }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 1207
        }, this),
        /* @__PURE__ */ jsxDEV("div", { className: "detail-label", children: [
          "OUTPUT / EVIDENCE ",
          e.payload?.exit_code !== void 0 && /* @__PURE__ */ jsxDEV(Badge, { tone: e.payload.exit_code === 0 ? "success" : "fail", children: [
            "EXIT ",
            e.payload.exit_code
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 39,
            columnNumber: 1333
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 1250
        }, this),
        /* @__PURE__ */ jsxDEV("pre", { children: typeof e.payload?.stdout === "string" ? e.payload.stdout : JSON.stringify(e.payload, null, 2) }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 39,
          columnNumber: 1429
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 39,
        columnNumber: 1033
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 39,
      columnNumber: 527
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 39,
    columnNumber: 294
  }, this);
}
function ClarifyCard({ question }) {
  const [value, setValue] = useState("");
  const [sent, setSent] = useState(false);
  return /* @__PURE__ */ jsxDEV("div", { className: "clarify-card", children: [
    /* @__PURE__ */ jsxDEV(MessageSquare, { size: 16 }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 40,
      columnNumber: 160
    }, this),
    /* @__PURE__ */ jsxDEV("div", { children: [
      /* @__PURE__ */ jsxDEV("b", { children: "Planner needs a clarification" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 40,
        columnNumber: 191
      }, this),
      /* @__PURE__ */ jsxDEV("p", { children: question }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 40,
        columnNumber: 227
      }, this),
      sent ? /* @__PURE__ */ jsxDEV("small", { className: "clarify-sent", children: "Reply sent to Planner" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 40,
        columnNumber: 250
      }, this) : /* @__PURE__ */ jsxDEV("div", { className: "clarify-input", children: [
        /* @__PURE__ */ jsxDEV("input", { value, onChange: (e) => setValue(e.target.value), placeholder: "Type your answer\u2026" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 40,
          columnNumber: 343
        }, this),
        /* @__PURE__ */ jsxDEV("button", { onClick: () => {
          if (value.trim()) setSent(true);
        }, "aria-label": "Send clarification", children: /* @__PURE__ */ jsxDEV(Send, { size: 13 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 40,
          columnNumber: 522
        }, this) }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 40,
          columnNumber: 436
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 40,
        columnNumber: 312
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 40,
      columnNumber: 186
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 40,
    columnNumber: 130
  }, this);
}
function TerminalView({ events, search, setSearch, sampleMode, toast }) {
  const lines = events.filter((e) => e.tool === "pytest" || e.event_type === "command.blocked");
  return /* @__PURE__ */ jsxDEV("div", { className: "terminal-view", children: [
    /* @__PURE__ */ jsxDEV("div", { className: "view-title", children: [
      /* @__PURE__ */ jsxDEV("div", { children: [
        /* @__PURE__ */ jsxDEV("h2", { children: "Command output" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 316
        }, this),
        /* @__PURE__ */ jsxDEV("p", { children: [
          "Sandbox execution stream ",
          /* @__PURE__ */ jsxDEV(Badge, { tone: "subtle", children: "READ ONLY" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 41,
            columnNumber: 367
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 339
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 41,
        columnNumber: 311
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "small-button", onClick: () => {
        navigator.clipboard?.writeText(lines.map((e) => String(e.payload.stdout || e.output_summary)).join("\n"));
        toast("Terminal output copied");
      }, children: [
        /* @__PURE__ */ jsxDEV(Copy, { size: 13 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 596
        }, this),
        " Copy"
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 41,
        columnNumber: 415
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 41,
      columnNumber: 283
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "terminal-controls", children: [
      /* @__PURE__ */ jsxDEV("label", { children: [
        /* @__PURE__ */ jsxDEV(Search, { size: 14 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 675
        }, this),
        /* @__PURE__ */ jsxDEV("input", { placeholder: "Search output", value: search, onChange: (e) => setSearch(e.target.value) }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 694
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 41,
        columnNumber: 668
      }, this),
      /* @__PURE__ */ jsxDEV("select", { children: [
        /* @__PURE__ */ jsxDEV("option", { children: "All commands" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 801
        }, this),
        /* @__PURE__ */ jsxDEV("option", { children: "Tests only" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 830
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 41,
        columnNumber: 793
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "icon-btn", children: /* @__PURE__ */ jsxDEV(Play, { size: 13 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 41,
        columnNumber: 895
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 41,
        columnNumber: 866
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 41,
      columnNumber: 633
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "terminal-window", children: [
      /* @__PURE__ */ jsxDEV("div", { className: "terminal-bar", children: [
        /* @__PURE__ */ jsxDEV("span", {}, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 990
        }, this),
        /* @__PURE__ */ jsxDEV("span", {}, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 997
        }, this),
        /* @__PURE__ */ jsxDEV("span", {}, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 1004
        }, this),
        /* @__PURE__ */ jsxDEV("b", { children: [
          "agent-shell ",
          /* @__PURE__ */ jsxDEV("i", { children: "\xB7" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 41,
            columnNumber: 1026
          }, this),
          " mini_shop"
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 1011
        }, this),
        /* @__PURE__ */ jsxDEV("code", { children: "bash \u2014 sandbox" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 1048
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 41,
        columnNumber: 960
      }, this),
      lines.length === 0 && /* @__PURE__ */ jsxDEV("div", { className: "terminal-empty", children: [
        "Awaiting command output",
        /* @__PURE__ */ jsxDEV("span", { className: "blink", children: "\u258D" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 1155
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 41,
        columnNumber: 1100
      }, this),
      lines.filter((e) => (e.output_summary + " " + (e.payload.stdout || "")).toLowerCase().includes(search.toLowerCase())).map((e, i) => {
        const bad = e.event_type === "command.blocked" || e.payload.exit_code === 1;
        return /* @__PURE__ */ jsxDEV("section", { className: bad ? "term-command bad" : "term-command", children: [
          /* @__PURE__ */ jsxDEV("div", { className: "term-meta", children: [
            /* @__PURE__ */ jsxDEV("span", { children: fmt(e.time) }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 41,
              columnNumber: 1484
            }, this),
            /* @__PURE__ */ jsxDEV("code", { children: e.tool === "pytest" ? "$ pytest -q" : e.tool === "curl" ? "$ curl \u2026" : "$ " + e.tool }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 41,
              columnNumber: 1510
            }, this),
            sampleMode && /* @__PURE__ */ jsxDEV(Badge, { tone: "sample", children: "SAMPLE DATA" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 41,
              columnNumber: 1608
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 41,
            columnNumber: 1457
          }, this),
          e.event_type === "command.blocked" ? /* @__PURE__ */ jsxDEV("div", { className: "blocked-box", children: [
            /* @__PURE__ */ jsxDEV(ShieldAlert, { size: 15 }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 41,
              columnNumber: 1718
            }, this),
            /* @__PURE__ */ jsxDEV("span", { children: [
              /* @__PURE__ */ jsxDEV("b", { children: "COMMAND BLOCKED" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 41,
                columnNumber: 1748
              }, this),
              /* @__PURE__ */ jsxDEV("small", { children: e.payload.reason }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 41,
                columnNumber: 1770
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 41,
              columnNumber: 1742
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 41,
            columnNumber: 1689
          }, this) : /* @__PURE__ */ jsxDEV(Fragment, { children: [
            /* @__PURE__ */ jsxDEV("pre", { children: e.payload.stdout }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 41,
              columnNumber: 1819
            }, this),
            /* @__PURE__ */ jsxDEV("div", { className: "exit-line", children: [
              /* @__PURE__ */ jsxDEV("span", { children: [
                "Process exited with code ",
                e.payload.exit_code
              ] }, void 0, true, {
                fileName: "<stdin>",
                lineNumber: 41,
                columnNumber: 1875
              }, this),
              /* @__PURE__ */ jsxDEV("span", { children: e.payload.duration }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 41,
                columnNumber: 1934
              }, this),
              /* @__PURE__ */ jsxDEV(Badge, { tone: bad ? "fail" : "success", children: bad ? "FAIL" : "PASS" }, void 0, false, {
                fileName: "<stdin>",
                lineNumber: 41,
                columnNumber: 1967
              }, this)
            ] }, void 0, true, {
              fileName: "<stdin>",
              lineNumber: 41,
              columnNumber: 1848
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 41,
            columnNumber: 1817
          }, this)
        ] }, i, true, {
          fileName: "<stdin>",
          lineNumber: 41,
          columnNumber: 1390
        }, this);
      })
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 41,
      columnNumber: 927
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 41,
    columnNumber: 252
  }, this);
}
function DiffView({ sampleMode }) {
  const [active, setActive] = useState("shop/checkout.py");
  const checkout = [["@@ -1,8 +1,18 @@", "h"], [" from decimal import Decimal, ROUND_HALF_UP", ""], [" def total(subtotal, coupon):", ""], ["-    return subtotal", "d"], ["+    subtotal = Decimal(str(subtotal))", "a"], ["+    discount = Decimal(str(coupon))", "a"], ['+    return max(Decimal("0.00"), (subtotal - discount).quantize(Decimal("0.01")))', "a"], ["+def apply_coupon(subtotal, code):", "a"], ["+    return total(subtotal, coupon_for(code))", "a"]];
  const config = [["@@ -8,4 +8,5 @@", "h"], [" import os", ""], ['-PAYMENTS_API_KEY = "sk_test_..."', "d"], ['+PAYMENTS_API_KEY = os.getenv("PAYMENTS_API_KEY", "")', "a"]];
  return /* @__PURE__ */ jsxDEV("div", { className: "diff-view", children: [
    /* @__PURE__ */ jsxDEV("div", { className: "view-title", children: [
      /* @__PURE__ */ jsxDEV("div", { children: [
        /* @__PURE__ */ jsxDEV("h2", { children: "Change review" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 42,
          columnNumber: 773
        }, this),
        /* @__PURE__ */ jsxDEV("p", { children: [
          "2 files changed ",
          /* @__PURE__ */ jsxDEV(Badge, { tone: "success", children: "+6" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 814
          }, this),
          " ",
          /* @__PURE__ */ jsxDEV(Badge, { tone: "fail", children: "\u22122" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 847
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 42,
          columnNumber: 795
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 42,
        columnNumber: 768
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "small-button", children: [
        /* @__PURE__ */ jsxDEV(GitBranch, { size: 13 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 42,
          columnNumber: 919
        }, this),
        " Unified"
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 42,
        columnNumber: 886
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 42,
      columnNumber: 740
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "diff-layout", children: [
      /* @__PURE__ */ jsxDEV("div", { className: "file-tree", children: [
        /* @__PURE__ */ jsxDEV("small", { children: "CHANGED FILES" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 42,
          columnNumber: 1020
        }, this),
        ["shop/checkout.py", "config.py"].map((f, i) => /* @__PURE__ */ jsxDEV("button", { className: active === f ? "active" : "", onClick: () => setActive(f), children: [
          /* @__PURE__ */ jsxDEV(FileText, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1171
          }, this),
          f,
          /* @__PURE__ */ jsxDEV("span", { className: i ? "amber" : "green", children: i ? "+1" : "\uFF0B5 \u22121" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1195
          }, this)
        ] }, f, true, {
          fileName: "<stdin>",
          lineNumber: 42,
          columnNumber: 1093
        }, this))
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 42,
        columnNumber: 993
      }, this),
      /* @__PURE__ */ jsxDEV("div", { className: "code-diff", children: [
        /* @__PURE__ */ jsxDEV("div", { className: "code-file-head", children: [
          /* @__PURE__ */ jsxDEV(FileText, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1330
          }, this),
          active,
          /* @__PURE__ */ jsxDEV("span", { children: sampleMode && /* @__PURE__ */ jsxDEV(Badge, { tone: "sample", children: "SAMPLE DATA" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1378
          }, this) }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1359
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 42,
          columnNumber: 1298
        }, this),
        (active === "config.py" ? config : checkout).map(([line, type], i) => /* @__PURE__ */ jsxDEV("div", { className: "diff-line " + type, children: [
          /* @__PURE__ */ jsxDEV("span", { children: i + 1 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1536
          }, this),
          /* @__PURE__ */ jsxDEV("span", { children: i + 1 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1554
          }, this),
          /* @__PURE__ */ jsxDEV("code", { children: line }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1572
          }, this),
          active === "config.py" && i === 2 && /* @__PURE__ */ jsxDEV("button", { className: "review-note", children: [
            /* @__PURE__ */ jsxDEV(MessageSquare, { size: 12 }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 42,
              columnNumber: 1653
            }, this),
            " Reviewer: move secret to env"
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1621
          }, this)
        ] }, i, true, {
          fileName: "<stdin>",
          lineNumber: 42,
          columnNumber: 1493
        }, this)),
        /* @__PURE__ */ jsxDEV("div", { className: "review-inline", children: [
          /* @__PURE__ */ jsxDEV("span", { children: "RV" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1757
          }, this),
          /* @__PURE__ */ jsxDEV("b", { children: "Reviewer" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1772
          }, this),
          /* @__PURE__ */ jsxDEV("p", { children: "Secret now loads from the environment. Safe to merge." }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 42,
            columnNumber: 1787
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 42,
          columnNumber: 1726
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 42,
        columnNumber: 1271
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 42,
      columnNumber: 964
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 42,
    columnNumber: 713
  }, this);
}
function ReportView({ sampleMode, exportReport }) {
  return /* @__PURE__ */ jsxDEV("div", { className: "report-view", children: [
    /* @__PURE__ */ jsxDEV("div", { className: "view-title", children: [
      /* @__PURE__ */ jsxDEV("div", { children: [
        /* @__PURE__ */ jsxDEV("h2", { children: "Evidence report" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 160
        }, this),
        /* @__PURE__ */ jsxDEV("p", { children: [
          "Run summary ",
          /* @__PURE__ */ jsxDEV("code", { children: "RUN_8F2A1C" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 43,
            columnNumber: 199
          }, this),
          " ",
          sampleMode && /* @__PURE__ */ jsxDEV(Badge, { tone: "sample", children: "SAMPLE DATA" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 43,
            columnNumber: 236
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 184
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 155
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "small-button", onClick: exportReport, children: [
        /* @__PURE__ */ jsxDEV(Download, { size: 14 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 343
        }, this),
        " Export Markdown"
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 287
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 43,
      columnNumber: 127
    }, this),
    /* @__PURE__ */ jsxDEV("section", { className: "report-section verified", children: [
      /* @__PURE__ */ jsxDEV("div", { className: "report-label", children: [
        /* @__PURE__ */ jsxDEV(CheckCircle2, { size: 16 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 470
        }, this),
        " VERIFIED ",
        /* @__PURE__ */ jsxDEV("span", { children: "4 EVIDENCE ITEMS" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 505
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 440
      }, this),
      [["pytest -q", "20 passed \xB7 0.41s"], ["Currency precision", "Decimal quantize \xB7 ROUND_HALF_UP"], ["Coupon bounds", "Negative total prevented"], ["Reviewer pass", "0 unresolved issues"]].map(([a, b]) => /* @__PURE__ */ jsxDEV("div", { className: "evidence-row", children: [
        /* @__PURE__ */ jsxDEV(Check, { size: 14 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 771
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          /* @__PURE__ */ jsxDEV("b", { children: a }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 43,
            columnNumber: 795
          }, this),
          /* @__PURE__ */ jsxDEV("small", { children: b }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 43,
            columnNumber: 805
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 789
        }, this),
        /* @__PURE__ */ jsxDEV(Badge, { tone: "success", children: "PASS" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 830
        }, this)
      ] }, a, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 733
      }, this))
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 43,
      columnNumber: 395
    }, this),
    /* @__PURE__ */ jsxDEV("section", { className: "report-section assumptions", children: [
      /* @__PURE__ */ jsxDEV("div", { className: "report-label", children: [
        /* @__PURE__ */ jsxDEV(AlertTriangle, { size: 16 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 960
        }, this),
        " NOT VERIFIED / ASSUMPTIONS ",
        /* @__PURE__ */ jsxDEV("span", { children: "1 ITEM" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1014
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 930
      }, this),
      /* @__PURE__ */ jsxDEV("div", { className: "evidence-row", children: [
        /* @__PURE__ */ jsxDEV(AlertTriangle, { size: 14 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1069
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          /* @__PURE__ */ jsxDEV("b", { children: "Live payment provider integration" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 43,
            columnNumber: 1101
          }, this),
          /* @__PURE__ */ jsxDEV("small", { children: "Not exercised in the sandbox." }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 43,
            columnNumber: 1141
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1095
        }, this),
        /* @__PURE__ */ jsxDEV(Badge, { tone: "amber", children: "ASSUMED" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1192
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 1039
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 43,
      columnNumber: 882
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "report-summary", children: [
      /* @__PURE__ */ jsxDEV("section", { children: [
        /* @__PURE__ */ jsxDEV("small", { children: "CHANGED FILES" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1284
        }, this),
        /* @__PURE__ */ jsxDEV("b", { children: "2 files" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1312
        }, this),
        /* @__PURE__ */ jsxDEV("code", { children: [
          "shop/checkout.py",
          /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 43,
            columnNumber: 1348
          }, this),
          "config.py"
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1326
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 1275
      }, this),
      /* @__PURE__ */ jsxDEV("section", { children: [
        /* @__PURE__ */ jsxDEV("small", { children: "RETRIES USED" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1388
        }, this),
        /* @__PURE__ */ jsxDEV("b", { children: [
          "1 ",
          /* @__PURE__ */ jsxDEV("em", { children: "/ 3" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 43,
            columnNumber: 1420
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1415
        }, this),
        /* @__PURE__ */ jsxDEV("code", { children: "1 loop \xB7 2 approaches" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1436
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 1379
      }, this),
      /* @__PURE__ */ jsxDEV("section", { children: [
        /* @__PURE__ */ jsxDEV("small", { children: "OPEN ISSUES" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1489
        }, this),
        /* @__PURE__ */ jsxDEV("b", { className: "green", children: "0" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1515
        }, this),
        /* @__PURE__ */ jsxDEV("code", { children: "Review complete" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 43,
          columnNumber: 1541
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 43,
        columnNumber: 1480
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 43,
      columnNumber: 1243
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 43,
    columnNumber: 98
  }, this);
}
function RightPanel({ events, attempts, sampleMode }) {
  const [criteria, setCriteria] = useState([true, true, true]), [json, setJson] = useState(true), [plan, setPlan] = useState(true);
  const messages = events.filter((e) => e.message_type).slice(-4).reverse();
  return /* @__PURE__ */ jsxDEV("div", { className: "right-content", children: [
    /* @__PURE__ */ jsxDEV("div", { className: "panel-section plan-section", children: [
      /* @__PURE__ */ jsxDEV("button", { className: "panel-title", onClick: () => setPlan(!plan), children: [
        /* @__PURE__ */ jsxDEV("span", { children: [
          /* @__PURE__ */ jsxDEV(Layers3, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 464
          }, this),
          " PLAN"
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 458
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          sampleMode && /* @__PURE__ */ jsxDEV(Badge, { tone: "signal", children: "PLAN REVISED" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 515
          }, this),
          /* @__PURE__ */ jsxDEV(ChevronDown, { size: 13 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 557
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 496
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 397
      }, this),
      plan && /* @__PURE__ */ jsxDEV(Fragment, { children: [
        /* @__PURE__ */ jsxDEV("div", { className: "plan-task", children: [
          /* @__PURE__ */ jsxDEV(Avatar, { a: "planner", size: 21 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 633
          }, this),
          /* @__PURE__ */ jsxDEV("span", { children: [
            /* @__PURE__ */ jsxDEV("b", { children: "Acceptance criteria" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 44,
              columnNumber: 670
            }, this),
            /* @__PURE__ */ jsxDEV("small", { children: "3 checks \xB7 3 met" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 44,
              columnNumber: 696
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 664
          }, this),
          /* @__PURE__ */ jsxDEV(CheckCircle2, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 734
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 606
        }, this),
        ["Apply valid coupon", "Round currency safely", "Prevent negative totals"].map((x, i) => /* @__PURE__ */ jsxDEV("div", { className: "criterion", children: [
          /* @__PURE__ */ jsxDEV("i", { className: criteria[i] ? "checked" : "", children: criteria[i] && /* @__PURE__ */ jsxDEV(Check, { size: 9 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 939
          }, this) }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 885
          }, this),
          /* @__PURE__ */ jsxDEV("span", { children: [
            x,
            /* @__PURE__ */ jsxDEV("small", { children: criteria[i] ? "Evidence: pytest \xB7 line " + (28 + i * 7) : "Not yet verified" }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 44,
              columnNumber: 970
            }, this)
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 961
          }, this)
        ] }, x, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 850
        }, this)),
        /* @__PURE__ */ jsxDEV("div", { className: "plan-revision", children: [
          /* @__PURE__ */ jsxDEV("b", { children: "\u21BB Plan revised" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1099
          }, this),
          /* @__PURE__ */ jsxDEV("small", { children: "round() \u2192 Decimal quantize" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1120
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 1068
        }, this),
        /* @__PURE__ */ jsxDEV("div", { className: "tasks", children: [
          /* @__PURE__ */ jsxDEV("small", { children: "TASKS" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1190
          }, this),
          [["Inspect checkout flow", "planner"], ["Implement coupon calculation", "developer"], ["Run tests & review", "verifier"]].map(([x, a]) => /* @__PURE__ */ jsxDEV("div", { children: [
            /* @__PURE__ */ jsxDEV(Avatar, { a, size: 19 }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 44,
              columnNumber: 1354
            }, this),
            /* @__PURE__ */ jsxDEV("span", { children: x }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 44,
              columnNumber: 1388
            }, this),
            /* @__PURE__ */ jsxDEV(Check, { size: 12 }, void 0, false, {
              fileName: "<stdin>",
              lineNumber: 44,
              columnNumber: 1404
            }, this)
          ] }, x, true, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1341
          }, this))
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 1167
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 604
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 44,
      columnNumber: 353
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "panel-section", children: [
      /* @__PURE__ */ jsxDEV("button", { className: "panel-title", onClick: () => setJson(!json), children: [
        /* @__PURE__ */ jsxDEV("span", { children: [
          /* @__PURE__ */ jsxDEV(FileJson2, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1544
          }, this),
          " SHARED STATE"
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 1538
        }, this),
        /* @__PURE__ */ jsxDEV(ChevronDown, { size: 13 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 1586
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 1477
      }, this),
      json && /* @__PURE__ */ jsxDEV("div", { className: "json-box", children: [
        /* @__PURE__ */ jsxDEV("code", { children: [
          /* @__PURE__ */ jsxDEV("span", { children: "{" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1658
          }, this),
          /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1676
          }, this),
          "\xA0 ",
          /* @__PURE__ */ jsxDEV("i", { children: "repo" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1683
          }, this),
          ": ",
          /* @__PURE__ */ jsxDEV("em", { children: '"mini_shop"' }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1696
          }, this),
          ",",
          /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1717
          }, this),
          "\xA0 ",
          /* @__PURE__ */ jsxDEV("i", { children: "retry_count" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1724
          }, this),
          ": ",
          /* @__PURE__ */ jsxDEV("b", { children: "1" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1744
          }, this),
          ",",
          /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1753
          }, this),
          "\xA0 ",
          /* @__PURE__ */ jsxDEV("i", { children: "coupon_mode" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1760
          }, this),
          ": ",
          /* @__PURE__ */ jsxDEV("em", { children: '"decimal"' }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1780
          }, this),
          ",",
          /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1799
          }, this),
          "\xA0 ",
          /* @__PURE__ */ jsxDEV("i", { children: "tests" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1806
          }, this),
          ": ",
          /* @__PURE__ */ jsxDEV("em", { children: '"20 passed"' }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1820
          }, this),
          ",",
          /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1841
          }, this),
          "\xA0 ",
          /* @__PURE__ */ jsxDEV("i", { children: "open_issues" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1848
          }, this),
          ": ",
          /* @__PURE__ */ jsxDEV("b", { children: "0" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1868
          }, this),
          /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1876
          }, this),
          /* @__PURE__ */ jsxDEV("span", { children: "}" }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 1881
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 1652
        }, this),
        /* @__PURE__ */ jsxDEV("small", { children: "UPDATED 00:41.2" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 1906
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 1626
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 44,
      columnNumber: 1446
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "panel-section", children: [
      /* @__PURE__ */ jsxDEV("div", { className: "panel-title static", children: [
        /* @__PURE__ */ jsxDEV("span", { children: [
          /* @__PURE__ */ jsxDEV(Activity, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 2022
          }, this),
          " ATTEMPTS"
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 2016
        }, this),
        /* @__PURE__ */ jsxDEV(Badge, { tone: "subtle", children: attempts.length }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 2059
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 1980
      }, this),
      /* @__PURE__ */ jsxDEV("div", { className: "attempt-list", children: attempts.map((a, i) => /* @__PURE__ */ jsxDEV("div", { children: [
        /* @__PURE__ */ jsxDEV("span", { children: String(i + 1).padStart(2, "0") }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 2175
        }, this),
        /* @__PURE__ */ jsxDEV("code", { children: a }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 2217
        }, this)
      ] }, i, true, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 2162
      }, this)) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 2111
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 44,
      columnNumber: 1949
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "panel-section board-section", children: [
      /* @__PURE__ */ jsxDEV("div", { className: "panel-title static", children: [
        /* @__PURE__ */ jsxDEV("span", { children: [
          /* @__PURE__ */ jsxDEV(MessageSquare, { size: 14 }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 2340
          }, this),
          " MESSAGE BOARD"
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 2334
        }, this),
        /* @__PURE__ */ jsxDEV("i", { className: "live-mini" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 2387
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 2298
      }, this),
      messages.length ? messages.map((e, i) => /* @__PURE__ */ jsxDEV("div", { className: "message", children: [
        /* @__PURE__ */ jsxDEV(Avatar, { a: e.agent, size: 20 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 2489
        }, this),
        /* @__PURE__ */ jsxDEV("span", { children: [
          /* @__PURE__ */ jsxDEV("b", { style: { color: colors[e.agent] }, children: e.agent }, void 0, false, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 2526
          }, this),
          /* @__PURE__ */ jsxDEV("small", { children: [
            e.message_type,
            " \xB7 ",
            e.output_summary
          ] }, void 0, true, {
            fileName: "<stdin>",
            lineNumber: 44,
            columnNumber: 2574
          }, this)
        ] }, void 0, true, {
          fileName: "<stdin>",
          lineNumber: 44,
          columnNumber: 2520
        }, this)
      ] }, i, true, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 2456
      }, this)) : /* @__PURE__ */ jsxDEV("div", { className: "board-empty", children: "Agent messages appear here" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 44,
        columnNumber: 2641
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 44,
      columnNumber: 2253
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 44,
    columnNumber: 322
  }, this);
}
function Approval({ onClose, approve, reject, setReject, reason, setReason, sampleMode }) {
  return /* @__PURE__ */ jsxDEV(motion.div, { className: "modal-shade", initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, children: /* @__PURE__ */ jsxDEV(motion.div, { className: "approval-modal", initial: { y: 24, opacity: 0 }, animate: { y: 0, opacity: 1 }, exit: { y: 24, opacity: 0 }, children: [
    /* @__PURE__ */ jsxDEV("div", { className: "modal-top", children: [
      /* @__PURE__ */ jsxDEV("div", { children: [
        /* @__PURE__ */ jsxDEV("span", { className: "eyebrow", children: "HUMAN REVIEW" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 476
        }, this),
        /* @__PURE__ */ jsxDEV("h2", { children: "Approve this mission?" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 521
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 471
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "icon-btn", onClick: onClose, children: /* @__PURE__ */ jsxDEV(X, { size: 17 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 604
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 557
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 45,
      columnNumber: 444
    }, this),
    /* @__PURE__ */ jsxDEV("p", { className: "modal-summary", children: "Coupon support added to checkout with safe currency rounding, a zero-total floor, and secret configuration cleanup." }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 45,
      columnNumber: 633
    }, this),
    sampleMode && /* @__PURE__ */ jsxDEV(Badge, { tone: "sample", children: "SAMPLE DATA \xB7 PREVIEW ONLY" }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 45,
      columnNumber: 794
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "approval-stats", children: [
      /* @__PURE__ */ jsxDEV("span", { children: [
        /* @__PURE__ */ jsxDEV(CheckCircle2, { size: 16 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 888
        }, this),
        /* @__PURE__ */ jsxDEV("b", { children: "20" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 913
        }, this),
        /* @__PURE__ */ jsxDEV("small", { children: "tests passed" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 922
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 882
      }, this),
      /* @__PURE__ */ jsxDEV("span", { children: [
        /* @__PURE__ */ jsxDEV(CheckCircle2, { size: 16 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 962
        }, this),
        /* @__PURE__ */ jsxDEV("b", { children: "3 / 3" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 987
        }, this),
        /* @__PURE__ */ jsxDEV("small", { children: "criteria met" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 999
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 956
      }, this),
      /* @__PURE__ */ jsxDEV("span", { children: [
        /* @__PURE__ */ jsxDEV(AlertTriangle, { size: 16 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1039
        }, this),
        /* @__PURE__ */ jsxDEV("b", { children: "0" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1065
        }, this),
        /* @__PURE__ */ jsxDEV("small", { children: "open issues" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1073
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 1033
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 45,
      columnNumber: 850
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "mini-diff", children: [
      /* @__PURE__ */ jsxDEV("small", { children: "DIFF PREVIEW \xB7 2 FILES CHANGED" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 1139
      }, this),
      /* @__PURE__ */ jsxDEV("code", { children: [
        /* @__PURE__ */ jsxDEV("i", { children: "+ Decimal quantize with ROUND_HALF_UP" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1190
        }, this),
        /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1234
        }, this),
        /* @__PURE__ */ jsxDEV("i", { children: '+ total = max(Decimal("0.00"), total)' }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1239
        }, this),
        /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1283
        }, this),
        /* @__PURE__ */ jsxDEV("del", { children: '\u2212 PAYMENTS_API_KEY = "sk_test_..."' }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1288
        }, this),
        /* @__PURE__ */ jsxDEV("br", {}, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1333
        }, this),
        /* @__PURE__ */ jsxDEV("i", { children: "+ PAYMENTS_API_KEY = os.getenv(...)" }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1338
        }, this)
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 1184
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 45,
      columnNumber: 1112
    }, this),
    reject && /* @__PURE__ */ jsxDEV("textarea", { className: "reject-reason", placeholder: "Reason for rejecting this change\u2026", value: reason, onChange: (e) => setReason(e.target.value) }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 45,
      columnNumber: 1402
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "modal-actions", children: [
      /* @__PURE__ */ jsxDEV("button", { className: "reject-button", onClick: () => {
        if (reject && reason.trim()) onClose();
        else setReject(true);
      }, children: reject ? "Send rejection" : "Reject" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 1574
      }, this),
      /* @__PURE__ */ jsxDEV("button", { className: "gold-button", onClick: approve, children: [
        /* @__PURE__ */ jsxDEV(Check, { size: 15 }, void 0, false, {
          fileName: "<stdin>",
          lineNumber: 45,
          columnNumber: 1773
        }, this),
        " Approve and apply"
      ] }, void 0, true, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 1723
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 45,
      columnNumber: 1543
    }, this),
    /* @__PURE__ */ jsxDEV("div", { className: "modal-foot", children: [
      /* @__PURE__ */ jsxDEV(LockKeyhole, { size: 11 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 45,
        columnNumber: 1852
      }, this),
      " Nothing is applied until you approve"
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 45,
      columnNumber: 1824
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 45,
    columnNumber: 328
  }, this) }, void 0, false, {
    fileName: "<stdin>",
    lineNumber: 45,
    columnNumber: 229
  }, this);
}
function Palette({ commands, close }) {
  const [q, setQ] = useState("");
  const rows = commands.filter((x) => x[0].toLowerCase().includes(q.toLowerCase()));
  return /* @__PURE__ */ jsxDEV(motion.div, { className: "palette-shade", initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, onClick: close, children: /* @__PURE__ */ jsxDEV(motion.div, { className: "palette", initial: { y: -14, scale: 0.98 }, animate: { y: 0, scale: 1 }, onClick: (e) => e.stopPropagation(), children: [
    /* @__PURE__ */ jsxDEV("div", { className: "palette-search", children: [
      /* @__PURE__ */ jsxDEV(Search, { size: 16 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 458
      }, this),
      /* @__PURE__ */ jsxDEV("input", { autoFocus: true, placeholder: "Search commands\u2026", value: q, onChange: (e) => setQ(e.target.value) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 477
      }, this),
      /* @__PURE__ */ jsxDEV("kbd", { children: "ESC" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 571
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 46,
      columnNumber: 426
    }, this),
    /* @__PURE__ */ jsxDEV("small", { children: "COMMANDS" }, void 0, false, {
      fileName: "<stdin>",
      lineNumber: 46,
      columnNumber: 591
    }, this),
    rows.map(([name, fn], i) => /* @__PURE__ */ jsxDEV("button", { onClick: () => {
      fn();
      close();
    }, children: [
      /* @__PURE__ */ jsxDEV("span", { children: i === 0 ? /* @__PURE__ */ jsxDEV(Activity, { size: 14 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 700
      }, this) : i < 4 ? /* @__PURE__ */ jsxDEV(ArrowRight, { size: 14 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 726
      }, this) : /* @__PURE__ */ jsxDEV(Zap, { size: 14 }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 750
      }, this) }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 687
      }, this),
      name,
      /* @__PURE__ */ jsxDEV("kbd", { children: "\u21B5" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 780
      }, this)
    ] }, name, true, {
      fileName: "<stdin>",
      lineNumber: 46,
      columnNumber: 639
    }, this)),
    /* @__PURE__ */ jsxDEV("div", { className: "palette-foot", children: [
      "Navigate ",
      /* @__PURE__ */ jsxDEV("kbd", { children: "\u2191\u2193" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 842
      }, this),
      " Select ",
      /* @__PURE__ */ jsxDEV("kbd", { children: "\u21B5" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 863
      }, this),
      " Close ",
      /* @__PURE__ */ jsxDEV("kbd", { children: "esc" }, void 0, false, {
        fileName: "<stdin>",
        lineNumber: 46,
        columnNumber: 882
      }, this)
    ] }, void 0, true, {
      fileName: "<stdin>",
      lineNumber: 46,
      columnNumber: 803
    }, this)
  ] }, void 0, true, {
    fileName: "<stdin>",
    lineNumber: 46,
    columnNumber: 309
  }, this) }, void 0, false, {
    fileName: "<stdin>",
    lineNumber: 46,
    columnNumber: 192
  }, this);
}
createRoot(document.getElementById("root")).render(/* @__PURE__ */ jsxDEV(App, {}, void 0, false, {
  fileName: "<stdin>",
  lineNumber: 47,
  columnNumber: 53
}));
