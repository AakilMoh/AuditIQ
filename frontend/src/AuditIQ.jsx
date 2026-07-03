import { useState, useRef, useEffect, useCallback } from "react";

// ─── DESIGN TOKENS ───────────────────────────────────────────────────────────
const T = {
  navy:    "#0A0F1E",
  card:    "#111827",
  panel:   "#1E293B",
  border:  "#1E293B",
  border2: "#2D3748",
  pass:    "#10B981",
  fail:    "#EF4444",
  warn:    "#F59E0B",
  accent:  "#6366F1",
  text:    "#F8FAFC",
  muted:   "#CBD5E1",
  dim:     "#94A3B8",
};

// ─── GLOBAL STYLES ────────────────────────────────────────────────────────────
const GlobalStyle = () => (
  <style>{`
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    #root {
      width: 100%;
      max-width: none;
      margin: 0;
      padding: 0;
      text-align: left;
    }

    body {
      background: ${T.navy};
      color: ${T.text};
      font-family: 'Space Grotesk', system-ui, sans-serif;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }

    ::-webkit-scrollbar { width: 4px; height: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: ${T.border2}; border-radius: 2px; }

    @keyframes pulse-ring {
      0%   { box-shadow: 0 0 0 0 rgba(99,102,241,0.4); }
      70%  { box-shadow: 0 0 0 8px rgba(99,102,241,0); }
      100% { box-shadow: 0 0 0 0 rgba(99,102,241,0); }
    }
    @keyframes scan-line {
      0%   { transform: translateY(-100%); opacity: 0.6; }
      100% { transform: translateY(100%); opacity: 0; }
    }
    @keyframes blink {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0; }
    }
    @keyframes slide-up {
      from { opacity: 0; transform: translateY(16px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes fade-in {
      from { opacity: 0; }
      to   { opacity: 1; }
    }
    @keyframes ekg-draw {
      from { stroke-dashoffset: 300; }
      to   { stroke-dashoffset: 0; }
    }
    .slide-up  { animation: slide-up 0.35s ease forwards; }
    .fade-in   { animation: fade-in 0.25s ease forwards; }

    button { cursor: pointer; font-family: inherit; }
    input, select { font-family: inherit; }
  `}</style>
);

// ─── PIPELINE STEPS CONFIG ───────────────────────────────────────────────────
const STEPS = [
  { key: "init",             label: "Initialise",   icon: "⬡" },
  { key: "database",         label: "Database",     icon: "⬡" },
  { key: "transcribing",     label: "Transcribe",   icon: "⬡" },
  { key: "transcript_ready", label: "Transcript",   icon: "⬡" },
  { key: "auditing",         label: "AI Audit",     icon: "⬡" },
  { key: "stream",           label: "Generating",   icon: "⬡" },
  { key: "verifying",        label: "Verify",       icon: "⬡" },
  { key: "complete",         label: "Complete",     icon: "⬡" },
];

const STEP_ORDER = STEPS.map(s => s.key);

// ─── UTILITY COMPONENTS ──────────────────────────────────────────────────────
const Badge = ({ children, color = T.accent, style = {} }) => (
  <span style={{
    display: "inline-flex", alignItems: "center", gap: 4,
    padding: "2px 10px", borderRadius: 4,
    background: color + "22", border: `1px solid ${color}44`,
    color, fontSize: 11, fontWeight: 600,
    fontFamily: "'JetBrains Mono', monospace",
    letterSpacing: "0.05em", textTransform: "uppercase",
    ...style
  }}>{children}</span>
);

const MonoText = ({ children, style = {} }) => (
  <span style={{ fontFamily: "'JetBrains Mono', monospace", ...style }}>
    {children}
  </span>
);

// ─── EKG SIGNATURE ELEMENT ───────────────────────────────────────────────────
const EKGTrace = ({ active = false, color = T.accent }) => (
  <svg width="60" height="24" viewBox="0 0 60 24" fill="none"
    style={{ opacity: active ? 1 : 0.2, transition: "opacity 0.4s" }}>
    <polyline
      points="0,12 8,12 12,4 16,20 20,4 24,12 28,12 36,12 40,6 44,18 48,12 60,12"
      stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
      fill="none"
      style={active ? {
        strokeDasharray: 300,
        strokeDashoffset: 0,
        animation: "ekg-draw 0.6s ease forwards"
      } : {}}
    />
  </svg>
);

// ─── SIDEBAR ─────────────────────────────────────────────────────────────────
const Sidebar = ({ screen, setScreen }) => {
  const navItems = [
    { id: "dashboard", label: "Dashboard",  icon: "▦" },
    { id: "audit",     label: "New Audit",  icon: "◈" },
    { id: "history",   label: "History",    icon: "≡" },
  ];

  return (
    <aside style={{
      width: 220, minHeight: "100vh", background: "#080D1A",
      borderRight: `1px solid ${T.border}`,
      display: "flex", flexDirection: "column",
      position: "fixed", left: 0, top: 0, bottom: 0, zIndex: 10,
    }}>
      <div style={{ padding: "28px 24px 24px", borderBottom: `1px solid ${T.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 6,
            background: `linear-gradient(135deg, ${T.accent}, #818CF8)`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14, fontWeight: 700, color: "#fff",
          }}>A</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: "-0.02em" }}>AuditIQ</div>
            <div style={{ fontSize: 10, color: T.muted, fontFamily: "'JetBrains Mono', monospace" }}>
              FDCPA Audit Engine
            </div>
          </div>
        </div>
      </div>

      <nav style={{ flex: 1, padding: "16px 12px" }}>
        {navItems.map(item => {
          const active = screen === item.id || (screen === "result" && item.id === "audit");
          return (
            <button key={item.id}
              onClick={() => setScreen(item.id)}
              style={{
                width: "100%", display: "flex", alignItems: "center", gap: 10,
                padding: "10px 12px", borderRadius: 6, border: "none",
                background: active ? `${T.accent}18` : "transparent",
                color: active ? T.accent : T.muted,
                fontSize: 13, fontWeight: active ? 600 : 400,
                marginBottom: 2, transition: "all 0.15s",
                borderLeft: active ? `2px solid ${T.accent}` : "2px solid transparent",
              }}>
              <span style={{ fontSize: 16 }}>{item.icon}</span>
              {item.label}
            </button>
          );
        })}
      </nav>

      <div style={{ padding: "16px 20px", borderTop: `1px solid ${T.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 7, height: 7, borderRadius: "50%", background: T.pass,
            animation: "pulse-ring 2s infinite",
          }} />
          <span style={{ fontSize: 11, color: T.muted }}>Engine online</span>
        </div>
        <div style={{ fontSize: 10, color: T.dim, marginTop: 4, fontFamily: "'JetBrains Mono', monospace" }}>
          v1.0 · Llama 70B
        </div>
      </div>
    </aside>
  );
};

// ─── DASHBOARD SCREEN ─────────────────────────────────────────────────────────
const DashboardScreen = ({ setScreen }) => {
  const [stats, setStats] = useState({
    audits_today: "—", compliance_rate: "—", violations_today: "—", average_score: "—"
  });
  const [recentCases, setRecentCases] = useState([]);

  useEffect(() => {
    fetch("http://localhost:8000/api/v1/logs/stats/summary")
      .then(res => res.json())
      .then(data => {
        if(data && typeof data.audits_today !== 'undefined') {
          setStats({
            audits_today: data.audits_today,
            compliance_rate: data.compliance_rate ? (data.compliance_rate * 100).toFixed(0) + "%" : "0%",
            violations_today: data.violations_today,
            average_score: data.average_score ? data.average_score.toFixed(1) : "0.0"
          });
        }
      }).catch(e => console.error("Failed to fetch stats", e));

    fetch("http://localhost:8000/api/v1/logs?limit=4")
      .then(res => res.json())
      .then(data => {
        if(data && Array.isArray(data)) {
            setRecentCases(data.map(log => {
                // If it's a raw SQL string, convert space to 'T' and append 'Z' to force UTC evaluation
                const parsedDate = log.timestamp.includes("T") 
                  ? new Date(log.timestamp) 
                  : new Date(log.timestamp.replace(" ", "T") + "Z");
                return {
                    name: log.account_name || `Debtor #${log.debtor_id}`,
                    score: log.ai_performance_score,
                    passed: log.compliance_passed,
                    time: parsedDate.toLocaleString()
                };
            }));
        }
      }).catch(e => console.error("Failed to fetch recent logs", e));
    }, []);
  const metrics = [
    { label: "Audits Today",       value: stats.audits_today,    sub: "Live from DB", color: T.accent },
    { label: "Compliance Rate",    value: stats.compliance_rate, sub: "Live from DB", color: T.pass   },
    { label: "Violations Flagged", value: stats.violations_today,sub: "Live from DB", color: T.fail   },
    { label: "Avg Score",          value: stats.average_score,   sub: "Live from DB", color: T.warn   },
  ];

  return (
    <div style={{ padding: "40px 48px", maxWidth: "1400px", margin: "0 auto"}} className="fade-in">
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace",
          letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
          QA REVIEW CONSOLE
        </div>
        <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.03em", marginBottom: 8 }}>
          Compliance Dashboard
        </h1>
        <p style={{ color: T.muted, fontSize: 14 }}>
          Real-time FDCPA audit monitoring across all debt collection agents.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(220px, 1fr))", gap: 16, marginBottom: 32 }}>
        {metrics.map((m, i) => (
          <div key={i} style={{
            background: T.card, border: `1px solid ${T.border2}`,
            borderRadius: 10, padding: "20px 24px",
            borderTop: `2px solid ${m.color}`,
          }}>
            <div style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 }}>
              {m.label}
            </div>
            <div style={{ fontSize: 32, fontWeight: 700, color: m.color, fontFamily: "'JetBrains Mono', monospace" }}>
              {m.value}
            </div>
            <div style={{ fontSize: 11, color: T.dim, marginTop: 6 }}>{m.sub}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "420px 1fr", gap: 20 }}>
        <div style={{
          background: `linear-gradient(135deg, ${T.accent}22, ${T.accent}08)`,
          border: `1px solid ${T.accent}44`, borderRadius: 12,
          padding: 32, display: "flex", flexDirection: "column", justifyContent: "space-between",
        }}>
          <div>
            <EKGTrace active color={T.accent} />
            <h2 style={{ fontSize: 22, fontWeight: 700, marginTop: 16, letterSpacing: "-0.02em" }}>
              Start New Audit
            </h2>
            <p style={{ color: T.muted, fontSize: 13, marginTop: 8, lineHeight: 1.6 }}>
              Upload a call recording and the AI pipeline will transcribe, analyse, and flag
              FDCPA violations in real-time.
            </p>
          </div>
          <button onClick={() => setScreen("audit")} style={{
            marginTop: 24, padding: "12px 24px", borderRadius: 8,
            background: T.accent, border: "none",
            color: "#fff", fontSize: 14, fontWeight: 600,
            transition: "opacity 0.15s",
          }}
            onMouseEnter={e => e.target.style.opacity = "0.85"}
            onMouseLeave={e => e.target.style.opacity = "1"}>
            Upload Recording →
          </button>
        </div>

        <div style={{
          background: T.card, border: `1px solid ${T.border2}`,
          borderRadius: 12, overflow: "hidden",
        }}>
          <div style={{ padding: "18px 24px", borderBottom: `1px solid ${T.border2}`,
            display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Recent Audits</span>
            <span style={{ fontSize: 11, color: T.dim, fontFamily: "'JetBrains Mono', monospace" }}>
              Live DB View
            </span>
          </div>
          {recentCases.length === 0 ? (
             <div style={{ padding: "24px", textAlign: "center", color: T.muted, fontSize: 13 }}>
                No audits have been performed yet.
             </div>
          ) : (
            recentCases.map((c, i) => (
              <div key={i} style={{
                padding: "14px 24px", borderBottom: i < recentCases.length - 1 ? `1px solid ${T.border}` : "none",
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{
                    width: 8, height: 8, borderRadius: "50%",
                    background: c.passed ? T.pass : T.fail, flexShrink: 0,
                  }} />
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{c.name}</div>
                    <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>{c.time}</div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <MonoText style={{ fontSize: 18, fontWeight: 700, color: c.passed ? T.pass : T.fail }}>
                    {c.score}/10
                  </MonoText>
                  <Badge color={c.passed ? T.pass : T.fail}>{c.passed ? "Pass" : "Fail"}</Badge>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

// ─── LIVE PIPELINE TRACE ──────────────────────────────────────────────────────
const PipelineTrace = ({ activeStep, statusMsg, error }) => {
  const activeIdx = STEP_ORDER.indexOf(activeStep);

  return (
    <div style={{
      background: T.card, border: `1px solid ${T.border2}`,
      borderRadius: 12, padding: "24px 20px",
    }}>
      <div style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 20 }}>
        Pipeline Status
      </div>

      {STEPS.map((step, i) => {
        const stepIdx  = STEP_ORDER.indexOf(step.key);
        const done     = stepIdx < activeIdx;
        const active   = step.key === activeStep;
        const upcoming = stepIdx > activeIdx;

        const color = error && active ? T.fail
          : done  ? T.pass
          : active ? T.accent
          : T.dim;

        return (
          <div key={step.key} style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 4 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 20, flexShrink: 0 }}>
              <div style={{
                width: 16, height: 16, borderRadius: "50%",
                border: `2px solid ${color}`,
                background: done ? color : active ? `${color}22` : "transparent",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 8, color: done ? "#fff" : color,
                transition: "all 0.3s",
                animation: active && !error ? "pulse-ring 1.5s infinite" : "none",
                flexShrink: 0,
              }}>
                {done ? "✓" : ""}
              </div>
              {i < STEPS.length - 1 && (
                <div style={{
                  width: 1, height: 28,
                  background: done ? T.pass : T.border2,
                  transition: "background 0.4s",
                }} />
              )}
            </div>

            <div style={{ paddingBottom: i < STEPS.length - 1 ? 12 : 0, paddingTop: 1 }}>
              <div style={{
                fontSize: 12, fontWeight: active ? 600 : 400,
                color: upcoming ? T.dim : color,
                transition: "color 0.3s",
                fontFamily: "'JetBrains Mono', monospace",
              }}>
                {step.label}
              </div>
              {active && statusMsg && (
                <div style={{ fontSize: 11, color: error ? T.fail : T.muted, marginTop: 2, lineHeight: 1.4 }}>
                  {statusMsg}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ─── NEW AUDIT SCREEN ─────────────────────────────────────────────────────────
const AuditScreen = ({ onResult }) => {
  const [file, setFile]           = useState(null);
  const [debtorId, setDebtorId]   = useState("");
  const [agentId, setAgentId]     = useState("");
  const [thinkMode, setThinkMode] = useState(false);
  const [dragging, setDragging]   = useState(false);

  const [liveDebtors, setLiveDebtors] = useState([]);
  const [liveAgents, setLiveAgents]   = useState([]);

  const [phase, setPhase]         = useState("idle"); 
  const [activeStep, setActiveStep]   = useState(null);
  const [statusMsg, setStatusMsg]     = useState("");
  const [transcript, setTranscript]   = useState("");
  const [streamBuffer, setStreamBuf]  = useState("");
  const [errorMsg, setErrorMsg]       = useState("");

  const streamRef = useRef(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [debtorsRes, agentsRes] = await Promise.all([
          fetch("http://localhost:8000/api/v1/debtors"),
          fetch("http://localhost:8000/api/v1/agents"),
        ]);

        if (!debtorsRes.ok || !agentsRes.ok) {
          throw new Error("Failed to fetch data");
        }

        const debtors = await debtorsRes.json();
        const agents = await agentsRes.json();

        setLiveDebtors(debtors);
        setLiveAgents(agents);

      } catch (error) {
        console.error("Error loading data:", error);
      }
    };

    fetchData();
  }, []);

  const handleFile = f => {
    if (f && (f.type.startsWith("audio/") || f.name.match(/\.(mp3|wav|m4a|ogg|flac|webm)$/i))) {
      setFile(f);
    }
  };

  const handleDrop = e => {
    e.preventDefault(); setDragging(false);
    handleFile(e.dataTransfer.files[0]);
  };

  const startAudit = async () => {
    if (!file || !debtorId || !agentId) return;
    setPhase("streaming");
    setActiveStep("init");
    setStatusMsg("Validating file and payload…");
    setTranscript("");
    setStreamBuf("");
    setErrorMsg("");

    const formData = new FormData();
    formData.append("audio_file", file);
    formData.append("debtor_id", debtorId);
    formData.append("agent_id", agentId);
    formData.append("think_mode", thinkMode ? "True" : "False");

    try {
      const res = await fetch("http://localhost:8000/api/v1/audit/stream", {
        method: "POST", body: formData,
      });

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer    = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (!payload) continue;

          let evt;
          try { evt = JSON.parse(payload); } catch { continue; }

          const step = evt.step;
          setActiveStep(step);

          if (step === "init")             setStatusMsg(evt.message);
          else if (step === "database")    setStatusMsg(evt.message);
          else if (step === "transcribing")setStatusMsg(evt.message);
          else if (step === "transcript_ready") {
            setTranscript(evt.transcript);
            setStatusMsg("Transcript ready");
          }
          else if (step === "auditing")    setStatusMsg(evt.message);
          else if (step === "stream")      setStreamBuf(p => p + (evt.chunk || ""));
          else if (step === "verifying")   setStatusMsg(evt.message);
          else if (step === "complete") {
            setPhase("idle");
            onResult(evt.result);
            
            // FIRE AND FORGET: Save to DB automatically!
            try {
                fetch("http://localhost:8000/api/v1/audit/save", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        debtor_id: parseInt(debtorId),
                        agent_id: parseInt(agentId),
                        result: evt.result
                    })
                });
            } catch(saveErr) {
                console.error("Failed to automatically save audit result to DB:", saveErr);
            }
          }
          else if (step === "error") {
            setPhase("error");
            setErrorMsg(evt.message);
          }
        }
      }
    } catch (err) {
      setPhase("error");
      setActiveStep("init");
      setErrorMsg(`Connection failed: ${err.message}`);
    }
  };

  const reset = () => {
    setPhase("idle"); setActiveStep(null); setStatusMsg("");
    setTranscript(""); setStreamBuf(""); setErrorMsg("");
    setFile(null); setDebtorId(""); setAgentId(""); setThinkMode(false);
  };

  const streaming = phase === "streaming";
  const hasError  = phase === "error";

  return (
    <div style={{ padding: "40px", display: "grid", gridTemplateColumns: "1fr 280px", gap: 24, alignItems: "start" }} className="fade-in">
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <div style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace",
            letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
            FDCPA Compliance Audit
          </div>
          <h1 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.02em" }}>
            New Audit
          </h1>
        </div>

        {!streaming && !hasError && (
          <div style={{ background: T.card, border: `1px solid ${T.border2}`, borderRadius: 12, overflow: "hidden" }}>
            <div style={{ padding: "20px 24px", borderBottom: `1px solid ${T.border2}` }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Upload Call Recording</span>
            </div>
            <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>

              <div
                onDragOver={e => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                onClick={() => document.getElementById("file-input").click()}
                style={{
                  border: `2px dashed ${file ? T.pass : dragging ? T.accent : T.border2}`,
                  borderRadius: 10, padding: "40px 24px",
                  textAlign: "center", cursor: "pointer",
                  background: dragging ? `${T.accent}08` : file ? `${T.pass}08` : "transparent",
                  transition: "all 0.2s",
                }}>
                <input id="file-input" type="file" accept="audio/*" style={{ display: "none" }}
                  onChange={e => handleFile(e.target.files[0])} />
                <div style={{ fontSize: 28, marginBottom: 10 }}>
                  {file ? "🎵" : "🎙️"}
                </div>
                {file ? (
                  <>
                    <div style={{ fontSize: 13, fontWeight: 600, color: T.pass }}>{file.name}</div>
                    <div style={{ fontSize: 11, color: T.muted, marginTop: 4 }}>
                      {(file.size / 1024 / 1024).toFixed(2)} MB · Click to change
                    </div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>Drop audio file here</div>
                    <div style={{ fontSize: 11, color: T.muted, marginTop: 4 }}>
                      mp3, wav, m4a, ogg, flac — or click to browse
                    </div>
                  </>
                )}
              </div>

              <div>
                <label style={{ fontSize: 12, color: T.muted, fontWeight: 500,
                  display: "block", marginBottom: 8, fontFamily: "'JetBrains Mono', monospace",
                  textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Debtor Account
                </label>
                <select value={debtorId} onChange={e => setDebtorId(e.target.value)} style={{
                  width: "100%", padding: "10px 14px",
                  background: T.panel, border: `1px solid ${T.border2}`,
                  borderRadius: 8, color: debtorId ? T.text : T.muted,
                  fontSize: 13, outline: "none",
                }}>
                  <option value="">Select debtor account…</option>
                  {liveDebtors.map(d => (
                    <option key={d.debtor_id} value={d.debtor_id}>
                      #{d.debtor_id} — {d.name} ({d.account_number} · ${d.balance})
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ marginTop: "-8px" }}>
                <label style={{ fontSize: 12, color: T.muted, fontWeight: 500,
                  display: "block", marginBottom: 8, fontFamily: "'JetBrains Mono', monospace",
                  textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Assigned Agent
                </label>
                <select value={agentId} onChange={e => setAgentId(e.target.value)} style={{
                  width: "100%", padding: "10px 14px",
                  background: T.panel, border: `1px solid ${T.border2}`,
                  borderRadius: 8, color: agentId ? T.text : T.muted,
                  fontSize: 13, outline: "none",
                }}>
                  <option value="">Select agent who made the call…</option>
                  {liveAgents.map(a => (
                    <option key={a.agent_id} value={a.agent_id}>
                      {a.name} — {a.department}
                    </option>
                  ))}
                </select>
              </div>

              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "14px 16px", background: T.panel, borderRadius: 8,
                border: `1px solid ${thinkMode ? T.accent + "44" : T.border2}`,
              }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>Think Mode</div>
                  <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>
                    Enables Llama 70B Chain-of-Thought — slower, deeper analysis
                  </div>
                </div>
                <div onClick={() => setThinkMode(p => !p)} style={{
                  width: 44, height: 24, borderRadius: 12, cursor: "pointer",
                  background: thinkMode ? T.accent : T.border2,
                  position: "relative", transition: "background 0.2s", flexShrink: 0,
                }}>
                  <div style={{
                    position: "absolute", top: 3,
                    left: thinkMode ? 23 : 3,
                    width: 18, height: 18, borderRadius: "50%",
                    background: "#fff", transition: "left 0.2s",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
                  }} />
                </div>
              </div>

              <button onClick={startAudit}
                disabled={!file || !debtorId || !agentId}
                style={{
                  padding: "13px", borderRadius: 8, border: "none",
                  background: file && debtorId && agentId ? T.accent : T.border2,
                  color: file && debtorId && agentId ? "#fff" : T.dim,
                  fontSize: 14, fontWeight: 600,
                  cursor: file && debtorId ? "pointer" : "not-allowed",
                  transition: "all 0.2s",
                }}>
                {file && debtorId ? "Run Audit →" : "Select file and debtor to continue"}
              </button>
            </div>
          </div>
        )}

        {hasError && (
          <div style={{
            background: `${T.fail}11`, border: `1px solid ${T.fail}44`,
            borderRadius: 12, padding: 24,
          }} className="slide-up">
            <div style={{ fontSize: 13, fontWeight: 600, color: T.fail, marginBottom: 8 }}>
              ⚠ Pipeline Error
            </div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6 }}>{errorMsg}</div>
            <button onClick={reset} style={{
              marginTop: 16, padding: "10px 20px", borderRadius: 6, border: `1px solid ${T.fail}`,
              background: "transparent", color: T.fail, fontSize: 13, fontWeight: 500,
            }}>
              Try Again
            </button>
          </div>
        )}

        {transcript && (
          <div style={{
            background: T.card, border: `1px solid ${T.border2}`,
            borderRadius: 12, overflow: "hidden",
          }} className="slide-up">
            <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border2}`,
              display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: T.pass }} />
              <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
                textTransform: "uppercase", letterSpacing: "0.06em" }}>Transcript</span>
            </div>
            <div style={{
              padding: "16px 20px", maxHeight: 240, overflowY: "auto",
              fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
              lineHeight: 1.7, color: T.muted, whiteSpace: "pre-wrap",
            }}>
              {transcript}
            </div>
          </div>
        )}

        {streaming && (
          <div style={{
            background: "#060B15", border: `1px solid ${T.border2}`,
            borderRadius: 12, overflow: "hidden",
          }} className="slide-up">
            <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border2}`,
              display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{
                  width: 8, height: 8, borderRadius: "50%", background: T.accent,
                  animation: "pulse-ring 1.2s infinite",
                }} />
                <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
                  textTransform: "uppercase", letterSpacing: "0.06em", color: T.accent }}>
                  AI Reasoning Stream
                </span>
              </div>
              <EKGTrace active color={T.accent} />
            </div>
            <div style={{
              padding: "16px 20px", maxHeight: 280, overflowY: "auto",
              fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
              lineHeight: 1.7, color: "#94A3B8", whiteSpace: "pre-wrap",
            }}>
              {streamBuffer.replace(/["{}\[\]]/g, '').replace(/reasoning:/i, 'REASONING:\n') || "Waiting for model output…"}
              {streamBuffer && (
                <span style={{ animation: "blink 1s infinite", color: T.accent }}>█</span>
              )}
            </div>
          </div>
        )}
      </div>

      <div style={{ position: "sticky", top: 24 }}>
        <PipelineTrace activeStep={activeStep} statusMsg={statusMsg} error={hasError} />

        {streaming && (
          <div style={{
            marginTop: 16, background: T.card, border: `1px solid ${T.border2}`,
            borderRadius: 10, padding: "14px 16px",
          }}>
            <div style={{ fontSize: 11, color: T.muted, marginBottom: 8,
              fontFamily: "'JetBrains Mono', monospace", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Model
            </div>
            <Badge color={thinkMode ? T.accent : T.muted}>
              {thinkMode ? "Llama 70B CoT" : "Standard"}
            </Badge>
          </div>
        )}
      </div>
    </div>
  );
};

// ─── RESULT SCREEN ────────────────────────────────────────────────────────────
const ResultScreen = ({ result, onNewAudit }) => {
  const [downloadingPDF, setDownloadingPDF] = useState(false);
  
  if (!result) return null;

  const handleDownloadPDF = async () => {
    setDownloadingPDF(true);
    try {
      const res = await fetch('http://localhost:8000/api/v1/audit/report/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(result),
      });
      if (!res.ok) throw new Error("PDF generation failed");
      
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `AuditIQ_${(result.account_name || 'Report').replace(/\s/g, "_")}_${Date.now()}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
      alert("Failed to download PDF report.");
    } finally {
      setDownloadingPDF(false);
    }
  };

  const {
    compliance_passed, performance_score, violations_found = [],
    reasoning = "", verification_notes = "", retrieved_rules = [],
    sql_facts = "", account_name = "", transcript = "",
  } = result;

  const verifierRejected = reasoning.startsWith("[REJECTED BY VERIFIER]:");
  const cleanReasoning   = verifierRejected
    ? reasoning.replace("[REJECTED BY VERIFIER]:", "").trim()
    : reasoning;

  const scoreColor =
    performance_score >= 8 ? T.pass :
    performance_score >= 5 ? T.warn : T.fail;

  return (
    <div style={{ padding: "40px" }} className="fade-in">
      <div style={{
        background: compliance_passed
          ? `linear-gradient(135deg, ${T.pass}18, ${T.pass}08)`
          : `linear-gradient(135deg, ${T.fail}18, ${T.fail}08)`,
        border: `1px solid ${compliance_passed ? T.pass + "44" : T.fail + "44"}`,
        borderRadius: 14, padding: "28px 32px", marginBottom: 24,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ fontSize: 40 }}>
            {compliance_passed ? "🛡" : "⚠"}
          </div>
          <div>
            <div style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
              Audit Verdict
            </div>
            <div style={{
              fontSize: 30, fontWeight: 700, letterSpacing: "-0.03em",
              color: compliance_passed ? T.pass : T.fail,
            }}>
              {compliance_passed ? "Compliant" : "Violation Detected"}
            </div>
            {account_name && (
              <div style={{ fontSize: 13, color: T.muted, marginTop: 4 }}>
                Account: <MonoText style={{ color: T.text }}>{account_name}</MonoText>
              </div>
            )}
          </div>
        </div>

        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace",
            letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
            Performance Score
          </div>
          <div style={{
            fontSize: 52, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace",
            color: scoreColor, lineHeight: 1,
          }}>
            {performance_score}
            <span style={{ fontSize: 20, color: T.muted }}>/10</span>
          </div>
          <EKGTrace active color={scoreColor} />
        </div>
      </div>

      {verifierRejected && (
        <div style={{
          background: `${T.warn}14`, border: `1px solid ${T.warn}55`,
          borderRadius: 10, padding: "14px 20px", marginBottom: 20,
          display: "flex", alignItems: "flex-start", gap: 12,
        }} className="slide-up">
          <span style={{ fontSize: 18, flexShrink: 0 }}>⚡</span>
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: T.warn,
              fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.06em",
              textTransform: "uppercase", marginBottom: 4 }}>
              Verifier Override Active
            </div>
            <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.5 }}>
              The secondary DeepSeek verifier detected a hallucination or logical inconsistency
              in the primary model's output. Score forced to 1/10.
            </div>
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
        <div style={{
          background: T.card, border: `1px solid ${violations_found.length ? T.fail + "44" : T.border2}`,
          borderRadius: 12, overflow: "hidden",
        }}>
          <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border2}`,
            display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%",
              background: violations_found.length ? T.fail : T.pass }} />
            <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
              textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Violations Found
            </span>
            <Badge color={violations_found.length ? T.fail : T.pass} style={{ marginLeft: "auto" }}>
              {violations_found.length || "None"}
            </Badge>
          </div>
          <div style={{ padding: "16px 20px" }}>
            {violations_found.length === 0 ? (
              <div style={{ fontSize: 13, color: T.pass, display: "flex", alignItems: "center", gap: 8 }}>
                <span>✓</span> No FDCPA violations detected
              </div>
            ) : (
              violations_found.map((v, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "flex-start", gap: 10,
                  padding: "8px 0", borderBottom: i < violations_found.length - 1 ? `1px solid ${T.border}` : "none",
                }}>
                  <span style={{ color: T.fail, fontSize: 14, flexShrink: 0 }}>✗</span>
                  <MonoText style={{ fontSize: 12, color: T.text, lineHeight: 1.5 }}>{v}</MonoText>
                </div>
              ))
            )}
          </div>
        </div>

        <div style={{ background: T.card, border: `1px solid ${T.border2}`, borderRadius: 12, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border2}`,
            display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: T.accent }} />
            <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
              textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Account Facts
            </span>
          </div>
          <div style={{ padding: "16px 20px" }}>
            <MonoText style={{ fontSize: 12, color: T.muted, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
              {sql_facts || "No account facts retrieved."}
            </MonoText>
          </div>
        </div>
      </div>

      <div style={{
        background: T.card,
        border: `1px solid ${verifierRejected ? T.warn + "55" : T.border2}`,
        borderRadius: 12, overflow: "hidden", marginBottom: 20,
      }}>
        <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border2}`,
          display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%",
            background: verifierRejected ? T.warn : T.accent }} />
          <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
            textTransform: "uppercase", letterSpacing: "0.06em" }}>
            AI Reasoning
          </span>
          {verifierRejected && <Badge color={T.warn} style={{ marginLeft: 8 }}>Rejected</Badge>}
        </div>
        <div style={{ padding: "20px", fontSize: 13, color: T.muted, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
          {cleanReasoning}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
        <div style={{ background: T.card, border: `1px solid ${T.border2}`, borderRadius: 12, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border2}` }}>
            <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
              textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Verifier Notes
            </span>
          </div>
          <div style={{ padding: "16px 20px", fontSize: 13, color: T.muted, lineHeight: 1.7 }}>
            {verification_notes || "No verifier notes."}
          </div>
        </div>

        <div style={{ background: T.card, border: `1px solid ${T.border2}`, borderRadius: 12, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border2}`,
            display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
              textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Retrieved Rules
            </span>
            <Badge color={T.accent}>{retrieved_rules.length}</Badge>
          </div>
          <div style={{ padding: "16px 20px", display: "flex", flexWrap: "wrap", gap: 8 }}>
            {retrieved_rules.length === 0
              ? <span style={{ fontSize: 12, color: T.dim }}>None retrieved.</span>
              : retrieved_rules.map((r, i) => (
                  <Badge key={i} color={T.accent}>{r}</Badge>
                ))
            }
          </div>
        </div>
      </div>

      {transcript && (
        <div style={{ background: T.card, border: `1px solid ${T.border2}`, borderRadius: 12, overflow: "hidden", marginBottom: 24 }}>
          <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border2}` }}>
            <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
              textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Full Transcript
            </span>
          </div>
          <div style={{
            padding: "16px 20px", maxHeight: 240, overflowY: "auto",
            fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
            lineHeight: 1.8, color: T.muted, whiteSpace: "pre-wrap",
          }}>
            {transcript}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 12 }}>
        <button onClick={onNewAudit} style={{
          padding: "12px 24px", borderRadius: 8, border: "none",
          background: T.accent, color: "#fff", fontSize: 13, fontWeight: 600,
        }}>
          ← New Audit
        </button>
        <button onClick={() => {
          const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
          const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
          a.download = `audit_${account_name?.replace(/\s/g,"_") || "result"}_${Date.now()}.json`;
          a.click();
        }} style={{
          padding: "12px 24px", borderRadius: 8,
          border: `1px solid ${T.border2}`, background: "transparent",
          color: T.muted, fontSize: 13, fontWeight: 500,
        }}>
          Export JSON ↓
        </button>

        <button onClick={handleDownloadPDF} disabled={downloadingPDF} style={{
          padding: "12px 24px", borderRadius: 8,
          border: `1px solid ${T.accent}55`, background: `${T.accent}11`,
          color: T.text, fontSize: 13, fontWeight: 600,
          cursor: downloadingPDF ? "wait" : "pointer",
          transition: "all 0.2s"
        }}>
          {downloadingPDF ? "Generating..." : "Download PDF 📄"}
        </button>
      </div>
    </div>
  );
};

// ─── HISTORY SCREEN ───────────────────────────────────────────────────────────
const HistoryScreen = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  const handleDownloadHistoricalPDF = async (logId, accountName) => {
    try {
      const res = await fetch(`http://localhost:8000/api/v1/audit/report/${logId}`);
      if (!res.ok) throw new Error("Failed to fetch PDF");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `AuditIQ_${(accountName || 'Report').replace(/\s/g, "_")}_Log${logId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
      alert("Failed to download historical PDF.");
    }
  };

  useEffect(() => {
    fetch("http://localhost:8000/api/v1/logs")
      .then(res => res.json())
      .then(data => { setLogs(data); setLoading(false); })
      .catch(err => { console.error("Failed to load logs:", err); setLoading(false); });
  }, []);

  return (
    <div style={{ padding: "40px" }} className="fade-in">
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace",
          letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
          Audit Log
        </div>
        <h1 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.02em" }}>History</h1>
      </div>

      <div style={{ background: T.card, border: `1px solid ${T.border2}`, borderRadius: 12, overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1.5fr 100px", padding: "16px 24px",
          borderBottom: `1px solid ${T.border2}`, fontSize: 12, fontWeight: 600, color: T.muted,
          textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: "'JetBrains Mono', monospace" }}>
          <div>Account</div>
          <div>Score</div>
          <div>Status</div>
          <div style={{ textAlign: "right" }}>Timestamp</div>
          <div></div> 
        </div>

        {loading ? (
          <div style={{ padding: "40px", textAlign: "center", color: T.muted }}>Loading logs...</div>
        ) : logs.length === 0 ? (
          <div style={{ padding: "40px", textAlign: "center", color: T.muted }}>No audits saved yet. Run an audit to see it here!</div>
        ) : (
          logs.map((log, i) => (
            <div key={log.log_id} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1.5fr 100px", padding: "16px 24px",
              borderBottom: i < logs.length - 1 ? `1px solid ${T.border}` : "none", alignItems: "center" }}>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{log.account_name || `Debtor #${log.debtor_id}`}</div>
              <div>
                <MonoText style={{ fontSize: 15, fontWeight: 700, color: log.compliance_passed ? T.pass : T.fail }}>
                  {log.ai_performance_score}/10
                </MonoText>
              </div>
              <div>
                <Badge color={log.compliance_passed ? T.pass : T.fail}>{log.compliance_passed ? "Pass" : "Fail"}</Badge>
              </div>
              <div style={{ textAlign: "right", fontSize: 12, color: T.dim }}>
                {(() => {
                  const parsedDate = log.timestamp.includes("T") 
                    ? new Date(log.timestamp) 
                    : new Date(log.timestamp.replace(" ", "T") + "Z");
                  return parsedDate.toLocaleString();
                })()}
              </div>
              <div style={{ textAlign: "right" }}>
                <button onClick={() => handleDownloadHistoricalPDF(log.log_id, log.account_name)} style={{
                  padding: "6px 12px", borderRadius: 6, border: `1px solid ${T.border2}`,
                  background: "transparent", color: T.accent, fontSize: 11, fontWeight: 600,
                  cursor: "pointer", transition: "all 0.2s"
                }}
                onMouseEnter={e => e.target.style.background = `${T.accent}11`}
                onMouseLeave={e => e.target.style.background = "transparent"}>
                  PDF ↓
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// ─── ROOT APP ─────────────────────────────────────────────────────────────────
export default function App() {
  const [screen, setScreen]   = useState("dashboard");
  const [result, setResult]   = useState(null);

  const handleResult = useCallback((r) => {
    setResult(r);
    setScreen("result");
  }, []);

  const handleNewAudit = useCallback(() => {
    setResult(null);
    setScreen("audit");
  }, []);

  return (
    <>
      <GlobalStyle />
      <div style={{ display: "flex", minHeight: "100vh" }}>
        <Sidebar screen={screen} setScreen={setScreen} />

        <main style={{ marginLeft: 220, flex: 1, minHeight: "100vh", width: "calc(100vw - 220px)", overflowX: "hidden",}}>
          {screen === "dashboard" && <DashboardScreen setScreen={setScreen} />}
          {screen === "audit"     && <AuditScreen onResult={handleResult} />}
          {screen === "result"    && <ResultScreen result={result} onNewAudit={handleNewAudit} />}
          {screen === "history"   && <HistoryScreen />}
        </main>
      </div>
    </>
  );
}