/* global React, ReactDOM, Dashboard, Topbar, TrustStrip, MethodologyView, ExplorerProView, TodayView, useTweaks, TweaksPanel, TweakSection, TweakRadio, TweakSelect, loadState */

const { useState, useEffect } = React;

const DEFAULTS = /*EDITMODE-BEGIN*/{
  "mode": "editorial",
  "fontDisplay": "Instrument Serif",
  "accent": "#d8ff5e"
}/*EDITMODE-END*/;

const FONT_OPTIONS = {
  "Instrument Serif": "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap",
  "Fraunces":         "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500&display=swap",
  "Newsreader":       "https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap",
  "Inter Tight":      "https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600&display=swap",
};

function App() {
  const [tab, setTab] = useState("today");
  const [tweaks, setTweak] = useTweaks(DEFAULTS);
  const [state, setState] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    loadState().then(setState).catch(e => setLoadError(String(e)));
  }, []);

  useEffect(() => { document.documentElement.dataset.mode = tweaks.mode; }, [tweaks.mode]);
  useEffect(() => {
    document.documentElement.style.setProperty("--accent", tweaks.accent);
    document.documentElement.style.setProperty("--font-display", `"${tweaks.fontDisplay}", Georgia, serif`);
    if (FONT_OPTIONS[tweaks.fontDisplay]) {
      const id = `font-${tweaks.fontDisplay.replace(/\s+/g, "-")}`;
      if (!document.getElementById(id)) {
        const l = document.createElement("link");
        l.rel = "stylesheet"; l.href = FONT_OPTIONS[tweaks.fontDisplay]; l.id = id;
        document.head.appendChild(l);
      }
    }
  }, [tweaks.accent, tweaks.fontDisplay]);

  if (loadError) {
    return <div style={{ padding: 40, color: "var(--warn)", fontFamily: "var(--font-mono)" }}>Failed to load state: {loadError}</div>;
  }
  if (!state) {
    return <div style={{ padding: 40, color: "var(--muted)", fontFamily: "var(--font-mono)" }}>Loading…</div>;
  }

  return (
    <div className="shell">
      <Topbar tab={tab} setTab={setTab} lastRun={state.lastRun} halt={state.halt} />
      <TrustStrip clock={state.paperTradeClock} />
      {tab === "today"       && <TodayView state={state} />}
      {tab === "dashboard"   && <Dashboard data={state} />}
      {tab === "explorer"    && <ExplorerProView state={state} />}
      {tab === "methodology" && <MethodologyView state={state} />}

      <TweaksPanel title="Tweaks">
        <TweakSection title="Direction">
          <TweakRadio label="Mode"
            value={tweaks.mode}
            options={[
              { value: "editorial", label: "Editorial" },
              { value: "terminal",  label: "Terminal" },
              { value: "soft",      label: "Soft" },
            ]}
            onChange={v => setTweak("mode", v)} />
        </TweakSection>
        <TweakSection title="Type">
          <TweakSelect label="Display font"
            value={tweaks.fontDisplay}
            options={Object.keys(FONT_OPTIONS).map(k => ({ value: k, label: k }))}
            onChange={v => setTweak("fontDisplay", v)} />
        </TweakSection>
        <TweakSection title="Color">
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {["#d8ff5e","#6ee7b7","#a78bfa","#fb923c","#60a5fa","#f472b6","#1a1d22"].map(c => (
              <button key={c} onClick={() => setTweak("accent", c)}
                      title={c}
                      style={{ width: 28, height: 28, borderRadius: 6, background: c, border: tweaks.accent === c ? "2px solid var(--ink)" : "1px solid var(--line)", cursor: "pointer" }} />
            ))}
          </div>
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
