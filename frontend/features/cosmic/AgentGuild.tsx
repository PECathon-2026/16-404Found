"use client";
import { AnimatePresence, motion } from "framer-motion";
import { Crown, Pause, Play, RotateCw } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Badge, cx } from "@/components/ui";
import { clock } from "@/lib/format";
import type { AgentRow, DevEvent, MissionDetail } from "@/lib/types";
import { AGENT_ORDER, GUILD, guild } from "./identity";

/**
 * 3D solar system. A real perspective projection, not stacked circles:
 *  - each agent orbits the orchestrator "sun" on an ellipse = a circle on a plane tilted by `tilt` toward the camera;
 *  - depth (sin of the orbital angle) drives planet scale and draw order, so planets pass in front of and behind the sun;
 *  - the pointer tilts the camera, hovering a planet freezes the system so it can be clicked;
 *  - an asteroid belt and the verifier's dashed outer orbit (a separate process) complete the picture.
 * Orbital motion is ambient. Whether an agent is working/failing/idle, and every message beam, come from real mission events.
 * One requestAnimationFrame loop moves ~6 elements through refs (no React re-renders per frame); it sleeps when hidden or off-screen.
 */
const sub = (cb: () => void) => { const t = setInterval(cb, 1000); return () => clearInterval(t); };
const useSeconds = () => useSyncExternalStore(sub, () => Math.floor(Date.now() / 1000), () => 0);

const BODY = [ // orbit radius (fraction of the largest), period (s), start angle (rad)
  { id: "planner", r: 0.34, period: 46, a0: -1.2 }, { id: "developer", r: 0.52, period: 62, a0: 2.4 }, { id: "tester", r: 0.68, period: 80, a0: 0.5 },
  { id: "security", r: 0.84, period: 104, a0: 4.1 }, { id: "verifier", r: 1.0, period: 140, a0: 5.4 },
] as const;
const ids = ["master", ...AGENT_ORDER] as const;

export function AgentGuild({ detail, events, live, onSelect, selected }: { detail: MissionDetail | null; events: DevEvent[]; live: boolean; onSelect: (id: string | null) => void; selected: string | null }) {
  const now = useSeconds() * 1000;
  const [hover, setHover] = useState<string | null>(null);
  const [spin, setSpin] = useState(true);
  const stage = useRef<HTMLDivElement>(null);
  const planetEl = useRef<Record<string, HTMLDivElement | null>>({});
  const ringEl = useRef<(SVGEllipseElement | null)[]>([]);
  const beltEl = useRef<SVGEllipseElement | null>(null);
  const lineEl = useRef<Record<string, SVGLineElement | null>>({});
  const bgEl = useRef<HTMLDivElement | null>(null);
  const sim = useRef({ phase: 0, last: 0, w: 0, h: 0, tilt: 62, tiltTarget: 62, nx: 0, freeze: false, reduced: false, visible: true, pos: {} as Record<string, { x: number; y: number }>, raf: 0 });
  const rows = useMemo(() => new Map<string, AgentRow>((detail?.agents ?? []).map((a) => [a.agent_id, a])), [detail]);

  const derived = useMemo(() => {
    const recentMsgs = events.filter((e) => e.type === "message.sent" && now - new Date(e.created_at).getTime() < 7000 && ids.includes(String(e.payload.sender) as never) && ids.includes(String(e.payload.recipient) as never)).slice(-6);
    const failing = new Set(events.filter((e) => (e.type === "tool.failed" || e.type === "policy.denied") && e.payload.error_code !== "ENV_MISSING_TOOL" && now - new Date(e.created_at).getTime() < 45000).map((e) => e.actor));
    const lastTool = new Map<string, DevEvent>();
    events.filter((e) => e.type === "tool.called").forEach((e) => lastTool.set(e.actor, e));
    return { recentMsgs, failing, lastTool };
  }, [events, now]);
  const working = (id: string) => rows.get(id as AgentRow["agent_id"])?.status === "thinking" || (id === "master" && !!detail && ["PLANNING", "EXECUTING", "VERIFYING"].includes(detail.status) && !AGENT_ORDER.some((a) => rows.get(a)?.status === "thinking"));
  const failed = (id: string) => derived.failing.has(id);
  const retries = detail?.counters.repair_cycles ?? 0;

  // freeze the system while the user is interacting with a planet or has paused it
  useEffect(() => { sim.current.freeze = !spin || hover !== null || selected !== null; }, [spin, hover, selected]);

  useEffect(() => {
    const s = sim.current, el = stage.current;
    if (!el) return;
    s.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ro = new ResizeObserver(() => { const b = el.getBoundingClientRect(); s.w = b.width; s.h = b.height; draw(); });
    const io = new IntersectionObserver(([e]) => { s.visible = e.isIntersecting; if (s.visible) loop(performance.now()); });
    ro.observe(el); io.observe(el);

    function draw() {
      const { w, h } = s; if (!w || !h) return;
      const cx = w / 2, cy = h / 2, cosT = Math.cos((s.tilt * Math.PI) / 180);
      const rMax = Math.min(w * 0.46, (h * 0.44) / Math.max(cosT, 0.3));
      BODY.forEach((b, i) => {
        const r = b.r * rMax, ang = b.a0 + (s.phase * 2 * Math.PI) / b.period;
        const x = cx + r * Math.cos(ang), y = cy + r * cosT * Math.sin(ang), depth = Math.sin(ang); // depth: +1 nearest the camera
        s.pos[b.id] = { x, y };
        const node = planetEl.current[b.id];
        if (node) { node.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`; node.style.zIndex = String(depth > 0 ? 25 : 8); node.style.setProperty("--s", String(0.78 + 0.34 * ((depth + 1) / 2))); node.style.opacity = String(0.72 + 0.28 * ((depth + 1) / 2)); node.style.visibility = "visible"; }
        const ring = ringEl.current[i];
        if (ring) { ring.setAttribute("cx", String(cx)); ring.setAttribute("cy", String(cy)); ring.setAttribute("rx", String(r)); ring.setAttribute("ry", String(r * cosT)); }
      });
      s.pos.master = { x: cx, y: cy };
      const sun = planetEl.current.master;
      if (sun) { sun.style.transform = `translate(${cx}px, ${cy}px) translate(-50%, -50%)`; sun.style.visibility = "visible"; sun.style.setProperty("--s", String(Math.min(1.25, Math.max(0.7, w / 760)))); }
      const belt = beltEl.current;
      if (belt) { const r = ((BODY[1].r + BODY[2].r) / 2) * rMax; belt.setAttribute("cx", String(cx)); belt.setAttribute("cy", String(cy)); belt.setAttribute("rx", String(r)); belt.setAttribute("ry", String(r * cosT)); }
      for (const ln of Object.values(lineEl.current)) {
        if (!ln) continue;
        const a = s.pos[ln.dataset.from ?? ""], b = s.pos[ln.dataset.to ?? ""];
        if (a && b) { ln.setAttribute("x1", String(a.x)); ln.setAttribute("y1", String(a.y)); ln.setAttribute("x2", String(b.x)); ln.setAttribute("y2", String(b.y)); }
      }
      if (bgEl.current) bgEl.current.style.transform = `translate3d(${-s.nx * 14}px, ${-(s.tilt - 62) * 1.2}px, 0) scale(1.06)`;
    }

    function loop(t: number) {
      cancelAnimationFrame(s.raf);
      if (!s.visible || document.hidden) { s.last = 0; return; }
      const dt = s.last ? Math.min((t - s.last) / 1000, 0.1) : 0;
      s.last = t;
      if (!s.reduced && !s.freeze) s.phase += dt;
      s.tilt += (s.tiltTarget - s.tilt) * Math.min(1, dt * 6); // ease the camera toward the pointer
      draw();
      if (!s.reduced) s.raf = requestAnimationFrame(loop); // reduced motion: draw once per resize/interaction, never animate
    }
    const move = (e: PointerEvent) => { const b = el.getBoundingClientRect(); s.nx = (e.clientX - b.left) / b.width - 0.5; s.tiltTarget = 62 + ((e.clientY - b.top) / b.height - 0.5) * 16; if (s.reduced) draw(); };
    const leave = () => { s.nx = 0; s.tiltTarget = 62; if (s.reduced) draw(); };
    const vis = () => { if (!document.hidden) { s.last = 0; loop(performance.now()); } };
    el.addEventListener("pointermove", move); el.addEventListener("pointerleave", leave); document.addEventListener("visibilitychange", vis);
    loop(performance.now());
    return () => { cancelAnimationFrame(s.raf); ro.disconnect(); io.disconnect(); el.removeEventListener("pointermove", move); el.removeEventListener("pointerleave", leave); document.removeEventListener("visibilitychange", vis); };
  }, []);

  const sel = selected ? guild(selected) : null;
  const selRow = selected ? rows.get(selected as AgentRow["agent_id"]) : undefined;
  const hid = { visibility: "hidden" as const };

  return (
    <div>
      <div ref={stage} className="relative mx-auto aspect-[4/3.3] max-h-[560px] min-h-[340px] w-full touch-pan-y overflow-hidden rounded-xl @container @2xl:aspect-[16/10]" role="group" aria-label="Agent guild: a 3D solar system where each agent is a planet orbiting the orchestrator" style={{ perspective: "900px" }}>
        {/* deep-space backdrop with parallax (moves opposite to the camera tilt) */}
        <div ref={bgEl} aria-hidden className="absolute -inset-4 will-change-transform" style={{ background: "radial-gradient(60% 80% at 0% 100%, rgba(59,130,246,.26), transparent 60%), radial-gradient(50% 60% at 100% 0%, rgba(139,92,246,.34), transparent 60%), radial-gradient(34% 34% at 50% 50%, rgba(251,191,36,.12), transparent 70%)" }}>
          <div className="absolute -bottom-28 -left-20 h-64 w-64 rounded-full bg-[radial-gradient(circle_at_70%_30%,#34498f,#0b1330_70%)] opacity-80 shadow-[0_0_90px_rgba(59,130,246,.3)]" />
          <div className="absolute -right-16 top-4 h-28 w-28 rounded-full bg-[radial-gradient(circle_at_35%_30%,#c4b5fd,#6d28d9_55%,#1e1038)] opacity-70 shadow-[0_0_50px_rgba(139,92,246,.4)]" />
        </div>

        <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
          <defs><filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter></defs>
          {BODY.map((b, i) => <ellipse key={b.id} ref={(n) => { ringEl.current[i] = n; }} fill="none" stroke={GUILD[b.id].color} strokeOpacity={b.id === "verifier" ? 0.32 : 0.2} strokeWidth="1" strokeDasharray={b.id === "verifier" ? "5 7" : undefined} />)}
          <ellipse ref={beltEl} fill="none" stroke="rgba(203,213,225,.55)" strokeWidth="2.4" strokeDasharray="0.5 7" strokeLinecap="round" opacity=".7">
            <animate attributeName="stroke-dashoffset" from="0" to="-300" dur="90s" repeatCount="indefinite" /></ellipse>
          {/* spokes + real message beams (positions are updated every frame as the planets move) */}
          {AGENT_ORDER.map((a) => <line key={`sp-${a}`} ref={(n) => { lineEl.current[`sp-${a}`] = n; }} data-from="master" data-to={a} stroke="rgba(148,163,184,.13)" strokeWidth="1" />)}
          {derived.recentMsgs.map((e) => {
            const peer = ["CRITIQUE", "CRITIQUE_RESPONSE", "QUESTION"].includes(String(e.payload.type));
            const col = peer ? "#fbbf24" : guild(String(e.payload.sender)).color;
            return <line key={e.id} ref={(n) => { lineEl.current[e.id] = n; }} className="flow-line" data-from={String(e.payload.sender)} data-to={String(e.payload.recipient)} stroke={col} strokeWidth="2.2" strokeLinecap="round" filter="url(#glow)" />;
          })}
        </svg>

        {/* the sun: the orchestrator */}
        <div ref={(n) => { planetEl.current.master = n; }} className="absolute left-0 top-0 z-[15]" style={hid}>
          <div style={{ scale: "var(--s)" }}>
            <button onClick={() => onSelect(selected === "master" ? null : "master")} aria-label="DevPilot Orchestrator" aria-pressed={selected === "master"} onMouseEnter={() => setHover("master")} onMouseLeave={() => setHover(null)}
              className="relative grid h-[118px] w-[118px] place-items-center rounded-full text-center transition-transform hover:scale-105">
              <span aria-hidden className="absolute -inset-10 rounded-full bg-[radial-gradient(circle,rgba(251,191,36,.38),rgba(249,115,22,.14)_45%,transparent_70%)]" style={{ animation: "dp-core 4s ease-in-out infinite" }} />
              <span aria-hidden className="planet absolute inset-0 bg-[radial-gradient(circle_at_35%_30%,#fff6c9,#fbbf24_36%,#ea7a0c_76%,#8a3a05)] shadow-[0_0_46px_8px_rgba(251,191,36,.55)]" />
              {working("master") && <span aria-hidden className="pulse-ring text-gold" />}
              <span className="relative flex flex-col items-center leading-tight text-[#2a1403]"><Crown className="h-5 w-5" aria-hidden /><span className="mt-0.5 text-base font-bold">DevPilot</span><span className="text-[11px] font-medium opacity-80">Orchestrator</span></span>
            </button>
          </div>
        </div>

        {/* planets */}
        {AGENT_ORDER.map((id, i) => {
          const g = GUILD[id], row = rows.get(id), run = working(id), bad = failed(id);
          return (
            <div key={id} ref={(n) => { planetEl.current[id] = n; }} className="absolute left-0 top-0" style={hid}>
              <div style={{ scale: "var(--s)" }}>
                <motion.button onClick={() => onSelect(selected === id ? null : id)} aria-pressed={selected === id} onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(id)} onBlur={() => setHover(null)}
                  whileHover={{ scale: 1.14 }} whileTap={{ scale: 0.95 }} initial={{ opacity: 0, scale: 0.4 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.15 + i * 0.1, type: "spring", stiffness: 160, damping: 14 }}
                  className="group flex flex-col items-center gap-1" aria-label={`${g.name}, ${g.role}: ${run ? "working" : bad ? "failing" : "idle"}`}>
                  <span className="relative grid h-12 w-12 place-items-center @lg:h-[62px] @lg:w-[62px]" style={{ color: bad ? "#f43f5e" : g.color }}>
                    {run && <span aria-hidden className="pulse-ring" />}
                    {id === "planner" && <span aria-hidden className="absolute -inset-3 rotate-[-18deg] rounded-[50%] border-2 border-gold/60" style={{ height: "36%", top: "32%", boxShadow: "0 0 10px rgba(251,191,36,.4)" }} />}
                    <span className="planet absolute inset-0" aria-hidden style={{ background: `radial-gradient(circle at 32% 28%, ${g.color}ee, ${g.color}aa 38%, #04060f 120%)`, boxShadow: `0 0 ${run ? 40 : 16}px rgba(${bad ? "244,63,94" : g.glow},${run ? 0.8 : 0.35}), inset -9px -11px 20px rgba(0,0,0,.55)`, border: bad ? "2px solid #f43f5e" : `1px solid ${g.color}88` }} />
                    <g.Icon className="relative h-5 w-5 text-white drop-shadow @lg:h-6 @lg:w-6" aria-hidden />
                    {id === "developer" && retries > 0 && <span className="absolute -right-2 -top-2 flex items-center gap-0.5 rounded-full border border-danger/60 bg-[#1a0b14] px-1.5 text-[10px] font-semibold text-danger" title={`${retries} repair cycle(s)`}><RotateCw className="h-2.5 w-2.5" aria-hidden />{retries}</span>}
                    {id === "verifier" && <span className="absolute -bottom-1.5 rounded-full border border-cyan/50 bg-black/70 px-1 text-[8px] uppercase tracking-wide text-cyan">isolated</span>}
                  </span>
                  <span className="text-center leading-tight"><span className="block text-xs font-semibold drop-shadow-[0_1px_4px_rgba(0,0,0,.9)] @lg:text-sm">{g.name}</span><span className="block text-[10px] text-fg2 @lg:text-[11px]">{g.role}</span>
                    <span className={cx("block text-[9px] font-semibold uppercase tracking-wide", run ? "text-cyan" : bad ? "text-danger" : "text-fg3")}>{run ? "working" : bad ? "failing" : row?.executions ? "idle" : "standby"}</span></span>
                </motion.button>
              </div>
              <AnimatePresence>{hover === id && (
                <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} role="tooltip" className="glass pointer-events-none absolute left-1/2 top-[88%] z-40 mt-1 w-52 -translate-x-1/2 rounded-lg p-2.5 text-left text-xs">
                  <div className="font-semibold">{g.name} <span className="font-normal text-fg3">({g.id})</span></div>
                  <div className="mt-1 text-fg2">{row?.executions ?? 0} run(s){row?.current_task_id ? " · on a task" : ""}</div>
                  {derived.lastTool.get(id) && <div className="mt-0.5 truncate font-mono text-[11px] text-fg3">last tool: {String(derived.lastTool.get(id)!.payload.tool)}</div>}
                  {row?.last_error && <div className="mt-0.5 text-danger">last error: {row.last_error.slice(0, 70)}</div>}</motion.div>)}</AnimatePresence>
            </div>);
        })}

        <div className="absolute left-3 top-3 z-30 flex items-center gap-2"><Badge tone={live ? "success" : "neutral"} icon={<span className={cx("h-1.5 w-1.5 rounded-full", live ? "dp-pulse bg-success" : "bg-neutral")} />}>{live ? "Live" : detail ? "Not connected" : "Idle"}</Badge></div>
        <button onClick={() => setSpin((v) => !v)} aria-pressed={!spin} aria-label={spin ? "Pause orbital motion" : "Resume orbital motion"} className="glass-flat absolute right-3 top-3 z-30 grid h-8 w-8 place-items-center rounded-full text-fg2 hover:text-fg">{spin ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}</button>
        <div className="pointer-events-none absolute bottom-2 left-3 z-30 hidden text-[10px] text-fg3 @lg:block">move the pointer to tilt the view · hover a planet to freeze the orbit</div>
      </div>

      <AnimatePresence initial={false}>{sel && (
        <motion.div key={sel.id} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-black/20 p-3 text-sm">
            <span className="grid h-9 w-9 place-items-center rounded-full" style={{ background: `${sel.color}33`, color: sel.color }}><sel.Icon className="h-4 w-4" aria-hidden /></span>
            <div className="min-w-0 flex-1"><div className="font-semibold">{sel.name} <span className="font-normal text-fg3">· {sel.role}</span></div>
              <div className="text-xs text-fg3">{selRow ? `${selRow.executions} run(s) · ${selRow.status === "thinking" ? "working now" : "idle"}` : "has not run in this mission"}{selRow?.last_error ? ` · last error: ${selRow.last_error.slice(0, 80)}` : ""}
                {derived.lastTool.get(sel.id) ? ` · last tool ${String(derived.lastTool.get(sel.id)!.payload.tool)} at ${clock(derived.lastTool.get(sel.id)!.created_at)}` : ""}</div></div>
            <span className="text-xs text-fg3">Activity feed filtered to this agent</span>
          </div></motion.div>)}</AnimatePresence>
    </div>
  );
}
