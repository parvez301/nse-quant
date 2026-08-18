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

/* ── The doc, line by line ─────────────────────────────────────────
   Each row: a literal quote from the shared DSRD workshop doc → how the
   simulation implemented it → what 43 months of data said. */
const DOC_AUDIT = [
  { quote: "Returns expectations - 15% - 30% per annum",
    simulated: "Measured net-of-cost CAGR on the judged window.",
    evidence: "2.7% per annum — a fixed deposit pays 7%. The top-20 variant made it −3.9%.",
    verdict: "REFUTED" },
  { quote: "Always make sure that the POP (probability of profit) is more than 60%",
    simulated: "Win rate across all 36 judged trades.",
    evidence: "77.8% — the claim is TRUE, and it's the trap: 28 wins averaged +₹6,596 while 8 losses averaged −₹16,809 (2.5× bigger). High POP, negative economics.",
    verdict: "TRUE BUT MISLEADING" },
  { quote: "We ONLY sell, ATM + 10% and ATM - 10% - THIS IS MANDATORY",
    simulated: "Strikes ≥8% from spot AND 0.10–0.20 delta (the refinement from the prompts doc), nearest 0.15 delta.",
    evidence: "The ±10% 'fence' was breached in 10 of 36 trades (27.8%). Breached trades averaged −₹10,587. A 1-in-4 failure rate is not a fence.",
    verdict: "IMPLEMENTED — FENCE FAILS 1-IN-4" },
  { quote: "Hippo stocks. Large Cap stocks. Top 10 STocks in terms of Market cap",
    simulated: "Full rerun of the judged window restricted to the 20 largest F&O names.",
    evidence: "−13.2% total, t-stat −2.78: statistically significant LOSSES. Calm giants pay tiny rent at 8% OTM but still gap on shocks.",
    verdict: "REFUTED" },
  { quote: "Just follow the trend, do not go against it. Use RSI",
    simulated: "RSI(14) computed at every entry; calm RSI earns up to 20/100 score points.",
    evidence: "All 36 entries had RSI between 43 and 57 (mean 50) — the system did trade only calm regimes, exactly as ordered. It lost anyway.",
    verdict: "IMPLEMENTED — DIDN'T SAVE IT" },
  { quote: "NEVER TRADE STOCK when the results are coming out of that stock",
    simulated: "Any cycle overlapping a quarterly-results window (SEBI's 45-day deadline) is skipped.",
    evidence: "Killed 22 of 43 cycles (51%). Rerunning with the filter OFF produced identical trades — the score floor already rejects those setups. Huge opportunity cost, zero measurable protection.",
    verdict: "IMPLEMENTED — REDUNDANT" },
  { quote: "Check if there is no Macro event. eg - WAR, election, Budget",
    simulated: "Hand-maintained blackout calendar: Budget days, general elections.",
    evidence: "Killed 8 more cycles (19%). Together with the earnings rule, the doc's own caution left only 13 of 43 months tradeable — the strategy spends 70% of its life in cash.",
    verdict: "IMPLEMENTED — 70% IDLE" },
  { quote: "Entry - When the contract begins... Build position on 1st friday of expiry. Observe Market for 1 hr",
    simulated: "Entered on the first Friday after the previous monthly expiry, at end-of-day settle prices.",
    evidence: "Faithfully followed. (The '1 hour observation' can't be simulated with daily data — disclosed, not skipped.)",
    verdict: "IMPLEMENTED" },
  { quote: "Exit/Target Price - Exit when 80% - 90% profit is realized",
    simulated: "Exit when remaining premium ≤ 20% of what was collected.",
    evidence: "Fired on 20 of 36 trades. The rule works mechanically — premium decay is real — the rent is just too small for the tail risk.",
    verdict: "CONFIRMED MECHANICALLY" },
  { quote: "Square off Last Tue or Wed... on the position of exipry",
    simulated: "Forced exit on the last Tuesday before expiry; never rides settlement.",
    evidence: "The other 16 of 36 trades exited here.",
    verdict: "IMPLEMENTED" },
  { quote: "Stop Loss- 1:1 SL - conservative... 1:2 SL - aggressive",
    simulated: "All variants tested on 2019–2022: 1:1, 1:1.5, 1:2, and none.",
    evidence: "Every stop level destroyed value (+2.5% to +3.8% vs +17.6% with no stop). Stops fired on premium spikes that then mean-reverted, locking losses plus panic-exit costs.",
    verdict: "REFUTED" },
  { quote: "Chasing and adjustment strategy can help",
    simulated: "Deliberately NOT simulated — the doc's own build-prompt #1 says 'Do not assume adjustment. Simply record event frequency.'",
    evidence: "Breach events recorded (27.8% of trades). Whether adjustment helps remains untested — but it would need to rescue a strategy already 4+ points of CAGR behind an FD.",
    verdict: "UNTESTED" },
  { quote: "The closer we get to expiry, the premium goes down",
    simulated: "Theta decay observed directly in the marks.",
    evidence: "True — 20 target exits are decay doing its job. The mechanism is real; the edge after costs is not.",
    verdict: "CONFIRMED" },
];

const VERDICT_STYLE = {
  "REFUTED":                    { color: "var(--sell)" },
  "TRUE BUT MISLEADING":        { color: "var(--hold)" },
  "IMPLEMENTED — FENCE FAILS 1-IN-4": { color: "var(--sell)" },
  "IMPLEMENTED — DIDN'T SAVE IT": { color: "var(--hold)" },
  "IMPLEMENTED — REDUNDANT":    { color: "var(--hold)" },
  "IMPLEMENTED — 70% IDLE":     { color: "var(--hold)" },
  "IMPLEMENTED":                { color: "var(--muted)" },
  "CONFIRMED MECHANICALLY":     { color: "var(--buy)" },
  "CONFIRMED":                  { color: "var(--buy)" },
  "UNTESTED":                   { color: "var(--faint)" },
};

function DocAudit() {
  return (
    <div className="card">
      <span className="t-eyebrow">The doc, line by line — every rule vs 43 months of data</span>
      <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 14 }}>
        Left: literal quotes from the shared strategy notes. Middle: how the simulation implemented that rule. Right: what actually happened.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {DOC_AUDIT.map(row => (
          <div key={row.quote} style={{ borderTop: "1px solid var(--line)", padding: "14px 0", display: "grid", gridTemplateColumns: "minmax(200px, 1fr) minmax(200px, 1fr) minmax(240px, 1.3fr)", gap: 18 }}>
            <div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 16, color: "var(--ink)", fontStyle: "italic" }}>“{row.quote}”</div>
              <span style={{ ...VERDICT_STYLE[row.verdict], fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.08em" }}>{row.verdict}</span>
            </div>
            <div style={{ color: "var(--ink-2)", fontSize: 13 }}>{row.simulated}</div>
            <div style={{ color: "var(--muted)", fontSize: 13 }}>{row.evidence}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Per-stock simulation explorer ────────────────────────────────
   Reads window.OPTIONS_DATA (generated by
   examples/nse_options_export_ui_data.py). */
const EXIT_NARRATIVE = {
  target: 'Doc rule fired: "Exit when 80–90% profit is realized." Premium decayed to ≤20% of what we collected — bought both legs back cheap.',
  time:   'Doc rule fired: "Square off Last Tue" — the profit target never arrived, so the position was force-closed on the last Tuesday before expiry.',
  stop:   "Stop-loss fired: combined premium blew past the stop multiple — bought back in a stressed market (double slippage charged).",
};

function TradeWalkthrough({ trade, index }) {
  const distancePct = (strike) => (Math.abs(strike - trade.entry_spot) / trade.entry_spot * 100).toFixed(1);
  const pnlColor = trade.net_pnl >= 0 ? "var(--buy)" : "var(--sell)";
  const money = (value) => `₹${Math.round(value).toLocaleString("en-IN")}`;
  const step = (label, body) => (
    <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 12, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
      <span className="t-eyebrow" style={{ paddingTop: 2 }}>{label}</span>
      <div style={{ fontSize: 13, color: "var(--ink-2)" }}>{body}</div>
    </div>
  );
  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--ink)" }}>
          Trade #{index + 1} · {trade.entry_date} → {trade.exit_date} · expiry {trade.expiry}
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 15, color: pnlColor }}>
          {trade.net_pnl >= 0 ? "+" : ""}{money(trade.net_pnl)}
        </span>
      </div>
      {step("1 · Entry", <>
        Doc: enter when the new monthly contract begins, first Friday. Entered {trade.entry_date} at closing prices.
        Spot <b style={{ color: "var(--ink)" }}>₹{trade.entry_spot?.toLocaleString("en-IN")}</b>
        {trade.rsi_at_entry != null && <> · RSI(14) <b style={{ color: "var(--ink)" }}>{trade.rsi_at_entry.toFixed(0)}</b> (doc wants calm — 45–55 is neutral)</>}
        {" "}· trade score {trade.score?.toFixed(0)}/100 (floor 75) · sigma grade <b style={{ color: "var(--ink)" }}>{trade.grade}</b>
      </>)}
      {step("2 · Strikes", <>
        Doc: sell ATM+10% call and ATM−10% put; prompts doc refines to 0.10–0.20 delta, ideal 0.15, never nearer than 8%.
        Sold CALL <b style={{ color: "var(--ink)" }}>{trade.call_strike}</b> ({distancePct(trade.call_strike)}% above, delta {trade.call_delta?.toFixed(3)}, IV {(trade.call_iv * 100).toFixed(0)}%)
        {" "}+ PUT <b style={{ color: "var(--ink)" }}>{trade.put_strike}</b> ({distancePct(trade.put_strike)}% below, delta {trade.put_delta?.toFixed(3)}, IV {(trade.put_iv * 100).toFixed(0)}%).
      </>)}
      {step("3 · Premium", <>
        Collected <b style={{ color: "var(--buy)" }}>{money(trade.premium_collected)}</b> ({trade.entry_premium_per_share?.toFixed(2)}/share × lot {trade.lot_size}),
        paying {money(trade.entry_costs)} in entry costs. Exchange blocked <b style={{ color: "var(--ink)" }}>{money(trade.margin)}</b> margin — this is why ₹1L capital can't play.
      </>)}
      {step("4 · Outcome", <>
        {EXIT_NARRATIVE[trade.exit_reason]}
        {" "}Bought back at {trade.exit_premium_per_share?.toFixed(2)}/share on {trade.exit_date} (exit costs {money(trade.exit_costs)}).
        {trade.breached && <b style={{ color: "var(--sell)" }}> ⚠ The ±10% fence FAILED on this trade — spot crossed a sold strike.</b>}
      </>)}
      {step("5 · Net", <>
        Gross {money(trade.gross_pnl)} − costs {money(trade.entry_costs + trade.exit_costs)} =
        <b style={{ color: pnlColor }}> {money(trade.net_pnl)}</b> on {money(trade.margin)} blocked
        {" "}(<b style={{ color: pnlColor }}>{(trade.net_pnl / trade.margin * 100).toFixed(1)}%</b> on margin for the cycle).
      </>)}
    </div>
  );
}

function StockExplorer() {
  const data = window.OPTIONS_DATA;
  const symbols = data ? Object.keys(data.trades_by_symbol).sort() : [];
  const [selectedSymbol, setSelectedSymbol] = React.useState(symbols[0] || "");
  if (!data) return null;
  const symbolTrades = data.trades_by_symbol[selectedSymbol] || [];
  const symbolNet = symbolTrades.reduce((sum, t) => sum + t.net_pnl, 0);
  return (
    <div className="card" style={{ background: "var(--surface)" }}>
      <span className="t-eyebrow">Walk through the simulation, stock by stock</span>
      <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 12 }}>
        Every trade the judged run took (2023 → Aug 2026), reconstructed step by step against the doc's rules. Pick a stock:
      </p>
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <select value={selectedSymbol} onChange={e => setSelectedSymbol(e.target.value)}
                style={{ background: "var(--surface-2)", color: "var(--ink)", border: "1px solid var(--line-strong)", borderRadius: 8, padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 14 }}>
          {symbols.map(symbol => {
            const net = data.trades_by_symbol[symbol].reduce((sum, t) => sum + t.net_pnl, 0);
            return <option key={symbol} value={symbol}>{symbol}  ({net >= 0 ? "+" : "−"}₹{Math.abs(Math.round(net)).toLocaleString("en-IN")})</option>;
          })}
        </select>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: symbolNet >= 0 ? "var(--buy)" : "var(--sell)" }}>
          {symbolTrades.length} trade{symbolTrades.length !== 1 ? "s" : ""} · net {symbolNet >= 0 ? "+" : "−"}₹{Math.abs(Math.round(symbolNet)).toLocaleString("en-IN")}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {symbolTrades.map((trade, index) => <TradeWalkthrough key={trade.entry_date + index} trade={trade} index={index} />)}
      </div>
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
      <DocAudit />
      <StockExplorer />
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
