/* global React */
/* OPTIONS tab — the DSRD short-strangle judge verdict, frozen 2026-08-18.
   All numbers are embedded (the study is a one-time finding, not live data);
   source of truth: outputs/options/judge/ in the repo. */

const OPTIONS_FINDINGS = {
  generatedAt: "2026-08-18",
  verdict: "FAIL",
  window: "Jan 2023 → Aug 2026 (43 months, walk-forward, never seen in tuning)",
  strategy: "Monthly short strangles on NSE stock options — sell ~0.15-delta call + put ≥8% OTM, exit at 80% premium or last Tuesday before expiry. Rules from the 'DSRD' workshop doc, tested exactly as written.",
  capitalNote: "Judged at ₹5,00,000 — the doc's ₹1,00,000 cannot margin even one stock strangle (median margin ₹1,12,560).",
  criteria: [
    { name: "Beat a fixed deposit (7% CAGR)", value: "2.7% CAGR", threshold: "> 7%", passed: false },
    { name: "Sharpe ≥ NIFTY buy-and-hold", value: "−0.58", threshold: "≥ 0.22", passed: false },
    { name: "Returns statistically real (t-stat > 2)", value: "−1.09", passed: false, threshold: "> 2" },
    { name: "Max drawdown < 30%", value: "9.9%", threshold: "< 30%", passed: true },
    { name: "Survive March-2020 replay (equity floor > 60%)", value: "96.6%", threshold: "> 60%", passed: true },
  ],
  headline: [
    { label: "Total return (3.6y)", value: "+10.0%", tone: "muted" },
    { label: "CAGR", value: "2.7%", tone: "bad" },
    { label: "Win rate", value: "77.8%", tone: "good" },
    { label: "Profit factor", value: "1.37", tone: "muted" },
    { label: "Trades", value: "36", tone: "muted" },
    { label: "±10% fence breached", value: "27.8%", tone: "bad" },
  ],
  perYear: [["2023", "−2.4%"], ["2024", "+6.1%"], ["2025", "+0.0%"], ["2026 YTD", "+6.3%"]],
  top20: {
    intro: "The workshop doc says: trade only the top-10/20 'hippo' large caps — calm giants, safer premiums. We reran the identical judged window restricted to the 20 largest F&O names. It is significantly WORSE:",
    rows: [
      ["Total return", "+10.0%", "−13.2%"],
      ["CAGR", "+2.7%", "−3.9%"],
      ["Sharpe", "−0.58", "−1.47"],
      ["t-stat", "−1.09", "−2.78 (significantly losing)"],
      ["Win rate", "77.8%", "79.2%"],
      ["Profit factor", "1.37", "0.50"],
      ["Max drawdown", "9.9%", "20.1%"],
      ["Trades", "36", "24"],
    ],
    why: "Giant stocks carry thin premiums at 8%+ OTM (low volatility = tiny rent), but they still gap on results, ratings, and macro shocks. The rare loss dwarfs the accumulated rent. Win rate stays near 80% — the illusion survives; the economics don't.",
  },
  stops: {
    intro: "Stop-losses — the doc's central safety rule — destroyed value at every level tested (tuning window 2019–2022):",
    rows: [["1:1 stop", "+2.5%", "−0.52"], ["1:1.5 stop", "+3.4%", "−0.43"],
           ["1:2 stop", "+3.8%", "−0.34"], ["No stop", "+17.6%", "−0.13"]],
    why: "Stops kept firing on temporary premium spikes that then mean-reverted — each trigger locked in a loss plus stressed exit costs. Even the best variant (no stop) trails a fixed deposit.",
  },
  attribution: {
    best: [["WIPRO", "+11,783"], ["ZEEL", "+11,383"], ["ADANIPORTS", "+10,839"], ["GAIL", "+10,278"], ["AARTIIND", "+9,439"]],
    worst: [["IEX", "−58,441"], ["CHAMBLFERT", "−14,979"], ["NMDC", "−10,169"], ["ASHOKLEY", "−8,905"], ["YESBANK", "−6,329"]],
    note: "One stock — IEX — erased six winners' worth of profit. This is short-premium asymmetry in miniature: many small wins, rare large losses.",
  },
  method: [
    "Data: every NSE stock-option contract's daily settle/OI, 2019 → Aug 2026 (1,877 trading days, from NSE's own Bhavcopy archives). IV and delta computed via Black-Scholes; spot from the F&O files themselves (never split-adjusted series).",
    "Honesty guards: stop-loss variant chosen ONLY on 2019–2022, judged ONLY on 2023+; dead/delisted names stay in the replay; full Indian retail costs (brokerage, STT, exchange, GST, stamp, slippage — doubled on stop exits); pass criteria written down before the run.",
    "Verdict rule: fail any one of five pre-registered criteria → the strategy is dead. It failed three.",
  ],
  takeaway: "Selling strangles the DSRD way earns less than a bank FD, with tail risk attached. High win rates are marketing, not edge. This finding cost ₹0 — the same lesson bought live is priced in lakhs.",
};

function VerdictBanner() {
  return (
    <div className="card" style={{ borderColor: "var(--sell)", background: "var(--sell-soft)" }}>
      <span className="t-eyebrow" style={{ color: "var(--sell)" }}>The judge's verdict</span>
      <div className="t-display" style={{ fontSize: 44, lineHeight: 1.05 }}>
        FAIL — it loses to a fixed deposit.
      </div>
      <p style={{ color: "var(--ink-2)", maxWidth: 720, marginTop: 10 }}>{OPTIONS_FINDINGS.strategy}</p>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 6 }}>
        Judged window: {OPTIONS_FINDINGS.window}. {OPTIONS_FINDINGS.capitalNote}
      </p>
    </div>
  );
}

function CriteriaCard() {
  return (
    <div className="card">
      <span className="t-eyebrow">Five pre-registered criteria — pass all or die</span>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <tbody>
          {OPTIONS_FINDINGS.criteria.map(criterion => (
            <tr key={criterion.name} style={{ borderTop: "1px solid var(--line)" }}>
              <td style={{ padding: "10px 8px 10px 0", color: "var(--ink-2)" }}>{criterion.name}</td>
              <td style={{ padding: "10px 8px", fontFamily: "var(--font-mono)", color: "var(--ink)" }}>{criterion.value}</td>
              <td style={{ padding: "10px 8px", color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{criterion.threshold}</td>
              <td style={{ padding: "10px 0", textAlign: "right" }}>
                <span style={{ color: criterion.passed ? "var(--buy)" : "var(--sell)", fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: "0.08em" }}>
                  {criterion.passed ? "PASS" : "FAIL"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatRow() {
  const toneColor = { good: "var(--buy)", bad: "var(--sell)", muted: "var(--ink)" };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "var(--gap)" }}>
      {OPTIONS_FINDINGS.headline.map(stat => (
        <div className="card" key={stat.label} style={{ padding: 16 }}>
          <span className="t-eyebrow">{stat.label}</span>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 26, color: toneColor[stat.tone] }}>{stat.value}</div>
        </div>
      ))}
    </div>
  );
}

function ComparisonCard({ title, intro, header, rows, why }) {
  return (
    <div className="card">
      <span className="t-eyebrow">{title}</span>
      <p style={{ color: "var(--ink-2)", fontSize: 14, marginBottom: 12 }}>{intro}</p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, fontFamily: "var(--font-mono)" }}>
          <thead>
            <tr>{header.map(cell => (
              <th key={cell} style={{ textAlign: "left", padding: "6px 12px 6px 0", color: "var(--muted)", fontWeight: 400, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" }}>{cell}</th>
            ))}</tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row[0]} style={{ borderTop: "1px solid var(--line)" }}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} style={{ padding: "8px 12px 8px 0", color: cellIndex === 0 ? "var(--ink-2)" : "var(--ink)" }}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 12 }}>{why}</p>
    </div>
  );
}

function AttributionCard() {
  const { best, worst, note } = OPTIONS_FINDINGS.attribution;
  const column = (title, rows, color) => (
    <div style={{ flex: 1, minWidth: 180 }}>
      <div className="t-eyebrow" style={{ marginBottom: 8 }}>{title}</div>
      {rows.map(([symbol, pnl]) => (
        <div key={symbol} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderTop: "1px solid var(--line)", fontFamily: "var(--font-mono)", fontSize: 13 }}>
          <span style={{ color: "var(--ink-2)" }}>{symbol}</span>
          <span style={{ color }}>₹{pnl}</span>
        </div>
      ))}
    </div>
  );
  return (
    <div className="card">
      <span className="t-eyebrow">Where the money went (judged window, net P&L)</span>
      <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
        {column("Best five", best, "var(--buy)")}
        {column("Worst five", worst, "var(--sell)")}
      </div>
      <p style={{ color: "var(--warn)", fontSize: 13, marginTop: 14 }}>{note}</p>
    </div>
  );
}

function OptionsView() {
  const findings = OPTIONS_FINDINGS;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)", padding: "0 var(--gap) var(--gap)" }}>
      <VerdictBanner />
      <StatRow />
      <CriteriaCard />
      <ComparisonCard
        title='"Just trade the top-20 hippo stocks" — tested'
        intro={findings.top20.intro}
        header={["Metric", "Full F&O universe", "Top-20 only"]}
        rows={findings.top20.rows}
        why={findings.top20.why} />
      <ComparisonCard
        title="Stop-losses made everything worse"
        intro={findings.stops.intro}
        header={["Variant", "Total (2019–22)", "Sharpe"]}
        rows={findings.stops.rows}
        why={findings.stops.why} />
      <AttributionCard />
      <div className="card">
        <span className="t-eyebrow">Per-year returns (judged)</span>
        <div style={{ display: "flex", gap: 28, fontFamily: "var(--font-mono)", fontSize: 15 }}>
          {findings.perYear.map(([year, value]) => (
            <div key={year}><span style={{ color: "var(--muted)", marginRight: 8 }}>{year}</span>{value}</div>
          ))}
        </div>
      </div>
      <div className="card">
        <span className="t-eyebrow">How this was tested (no cherry-picking)</span>
        {findings.method.map((paragraph, index) => (
          <p key={index} style={{ color: "var(--ink-2)", fontSize: 14, marginBottom: 8 }}>{paragraph}</p>
        ))}
        <p style={{ color: "var(--ink)", fontSize: 15, marginTop: 14, borderLeft: "3px solid var(--accent)", paddingLeft: 12 }}>
          {findings.takeaway}
        </p>
        <p style={{ color: "var(--faint)", fontSize: 12, marginTop: 10 }}>
          Frozen {findings.generatedAt} · full data & code: github.com/parvez301/nse-quant (options/, outputs/options/judge/)
        </p>
      </div>
    </div>
  );
}

window.OptionsView = OptionsView;
