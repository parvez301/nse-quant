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
    { name: "Beat a fixed deposit (7% CAGR)", value: "2.7% CAGR", threshold: "> 7%", passed: false,
      hint: "An FD is the zero-effort, zero-risk alternative. Earning less than it means the risk paid negative rent." },
    { name: "Sharpe ≥ NIFTY buy-and-hold", value: "−0.58", threshold: "≥ 0.22", passed: false,
      hint: "Was the stress worth it versus just buying the index and sleeping? Negative Sharpe = the FD alone beat this." },
    { name: "Returns statistically real (t-stat > 2)", value: "−1.09", passed: false, threshold: "> 2",
      hint: "Is the average profit skill or coin-flip luck? Above +2 = confidently real. This is below zero." },
    { name: "Max drawdown < 30%", value: "9.9%", threshold: "< 30%", passed: true,
      hint: "Worst peak-to-valley fall of the account. Passed — mostly because the strategy sat in cash 70% of the time." },
    { name: "Survive March-2020 replay (equity floor > 60%)", value: "96.6%", threshold: "> 60%", passed: true,
      hint: "Stress test: replay the COVID crash month. Passed for the same reason — barely any exposure." },
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

function SectionHeader({ number, title, sub }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 14, margin: "18px 4px 2px" }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--accent)" }}>{number}</span>
      <div>
        <div className="t-display" style={{ fontSize: 26 }}>{title}</div>
        {sub && <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 2 }}>{sub}</div>}
      </div>
    </div>
  );
}

function IdeaCard() {
  return (
    <div className="card">
      <span className="t-eyebrow">The strategy, as shared (no math needed)</span>
      <p style={{ color: "var(--ink-2)", fontSize: 14, maxWidth: 780 }}>
        Be the insurance seller. Every month, pick a calm large-cap stock and sell two promises:
        one that pays out if the stock <b style={{ color: "var(--ink)" }}>rises more than ~10%</b>, one if it{" "}
        <b style={{ color: "var(--ink)" }}>falls more than ~10%</b> (a "short strangle"). Collect both fees upfront.
        If the stock stays inside that ±10% fence for the month — which calm stocks usually do — both promises
        expire worthless and the fees are pure profit. Rules to stay safe: only big liquid "hippo" stocks,
        never in a results month, never around elections or the Budget, take profit once 80–90% of the fee is
        earned, square off before expiry, keep a stop-loss. Expected: 15–30% a year of steady rent.
      </p>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 8 }}>
        It's a genuinely popular idea — the "volatility risk premium" is real, and prop desks do harvest it.
        The question is whether it survives <i>retail costs, retail capital, and the occasional storm</i>. That's testable.
      </p>
    </div>
  );
}

function WhatWeDidCard() {
  const steps = [
    ["1 · We bought the history books",
     "Every NSE stock-option price, every trading day, 2019 → Aug 2026 (1,877 days) straight from NSE's own archives — including the COVID crash. Dead companies stay in; nothing is quietly forgotten."],
    ["2 · We coded the rules exactly as written",
     "A program plays the strategy with no feelings and no hindsight: same entry day, same ±10% strikes, same profit-taking and square-off rules, on paper money — charged full real-world costs (brokerage, STT, GST, exchange fees, slippage) on every leg."],
    ["3 · We wrote the pass marks BEFORE the exam",
     "Five pass/fail criteria were fixed in advance — beat a fixed deposit, beat lazy NIFTY, real (not lucky) profits, limited worst-case fall, survive March 2020. And to prevent grading our own homework, any tuning happened only on 2019–2022; the verdict below comes exclusively from 2023 onwards, which the tuning never saw."],
  ];
  return (
    <div className="card">
      <span className="t-eyebrow">Three steps, no jargon</span>
      {steps.map(([title, body]) => (
        <div key={title} style={{ borderTop: "1px solid var(--line)", padding: "10px 0" }}>
          <div style={{ color: "var(--ink)", fontSize: 14, marginBottom: 3 }}>{title}</div>
          <div style={{ color: "var(--muted)", fontSize: 13, maxWidth: 820 }}>{body}</div>
        </div>
      ))}
    </div>
  );
}

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
              <td style={{ padding: "10px 8px 10px 0" }}>
                <div style={{ color: "var(--ink-2)" }}>{criterion.name}</div>
                <div style={{ color: "var(--faint)", fontSize: 12, marginTop: 3, maxWidth: 460 }}>{criterion.hint}</div>
              </td>
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

/* ── Metric dictionary ─────────────────────────────────────────────
   Plain words first, then the EXACT formula this study used — so the
   definitions can't be accused of shifting to flatter the verdict. */
const METRIC_GLOSSARY = [
  { term: "CAGR",
    plain: "If the whole 3.6-year ride were flattened into identical years, this is what each year would earn — compounding included. The number to compare against an FD's 7%.",
    exact: "(final equity ÷ starting ₹5,00,000) ^ (12 ÷ 43 months) − 1. Equity marks realized + unrealized P&L daily; capital is constant (no reinvestment), which flatters the strategy if anything." },
  { term: "Sharpe ratio",
    plain: "Reward per unit of stomach-churn. Take what you earned ABOVE a fixed deposit, divide by how wildly the monthly results swung. Rough scale: below 0 = the FD beat you, ~1 = good, ~2 = excellent.",
    exact: "mean(monthly return − 7%/12) ÷ stdev(same), × √12 to annualize. Same formula applied to NIFTY's months for the benchmark (0.22)." },
  { term: "t-statistic",
    plain: "How confident we are the average isn't luck. Think of it as a signal-to-noise score: above +2 ≈ statistically real profits; between −2 and +2 = can't distinguish from coin flips; below −2 = reliably LOSING (the top-20 variant hit −2.78).",
    exact: "mean monthly excess ÷ (stdev ÷ √43 months). Only judged-window months count — the 2019–22 tuning years never enter the inference." },
  { term: "Max drawdown",
    plain: "The worst 'peak to valley' fall — if you'd joined at the best moment and looked at the worst one, how much of the account had melted.",
    exact: "max over time of (running-peak equity − equity) ÷ running-peak equity." },
  { term: "Win rate & profit factor",
    plain: "Win rate: how often trades ended green (77.8% — sounds great). Profit factor: total ₹ won ÷ total ₹ lost — the number win rate hides. Below 1.0 means losses outweigh wins regardless of how often you win.",
    exact: "wins ÷ trades; Σ(winning net P&L) ÷ |Σ(losing net P&L)|. Full universe: 1.37. Top-20: 0.50 — ₹2 lost per ₹1 won." },
  { term: "Delta",
    plain: "Roughly, the market's odds the option finishes worth something. Selling a 0.15-delta option ≈ collecting rent on an ~15%-chance event.",
    exact: "Black-Scholes N(d1) (calls) / N(d1)−1 (puts), at the entry-day settle-implied volatility, r = 7%." },
  { term: "Implied volatility (IV)",
    plain: "The market's forecast of how much the stock will move in a year, decoded from the option's price. 30% IV on a ₹1,000 stock ≈ 'typical year moves ±₹300'.",
    exact: "Bisection-inverted Black-Scholes on the EOD settle price; inversions that don't converge disqualify the contract rather than guessing." },
  { term: "1σ / 2σ bands",
    plain: "The 'probably stays inside' range: ~68% of the time within 1σ, ~95% within 2σ — IF the market's volatility guess is right. We only sold strangles whose strikes sat outside 1σ (grade A) or 2σ (grade A+).",
    exact: "spot × IV × √(days-to-expiry ÷ 365), doubled for 2σ." },
  { term: "Premium & theta",
    plain: "Premium is the rent collected upfront for selling the insurance. Theta is why it shrinks a little every quiet day — time passing is the seller's only friend.",
    exact: "Entry premium = both legs' settle × lot size; decay observed directly in daily marks (20 of 36 trades reached the 80% decay target)." },
  { term: "Margin",
    plain: "The security deposit the exchange locks while your promise is open. It's why ₹1L capital can't play: the median strangle blocked ₹1.13L.",
    exact: "SPAN proxy: worst leg = lot × max(20% spot − OTM amount, 10% spot), + 5%-of-spot add-on for the paired leg." },
  { term: "Breach",
    plain: "The stock crossing one of your sold strikes — the ±10% fence failing. Happened on 10 of 36 trades; those trades averaged −₹10,587.",
    exact: "Any daily spot mark ≥ call strike or ≤ put strike during the trade's life." },
];

function GlossaryCard() {
  return (
    <div className="card">
      <span className="t-eyebrow">Dictionary — what these numbers mean (and exactly how we computed them)</span>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "16px 28px", marginTop: 4 }}>
        {METRIC_GLOSSARY.map(entry => (
          <div key={entry.term} style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--accent)", letterSpacing: "0.04em", marginBottom: 4 }}>{entry.term}</div>
            <div style={{ color: "var(--ink-2)", fontSize: 13, marginBottom: 6 }}>{entry.plain}</div>
            <div style={{ color: "var(--faint)", fontSize: 12 }}><span style={{ color: "var(--muted)" }}>Our definition:</span> {entry.exact}</div>
          </div>
        ))}
      </div>
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

/* ── The friend's follow-up spreadsheet, simulated ─────────────── */
function SheetStudyCard() {
  const study = window.OPTIONS_DATA && window.OPTIONS_DATA.sheet_study;
  if (!study) return null;
  const money = (value) => `${value < 0 ? "−" : "+"}₹${Math.abs(value).toLocaleString("en-IN")}`;
  return (
    <div className="card">
      <span className="t-eyebrow">The follow-up spreadsheet — his 13 large caps, checked with real option prices</span>
      <p style={{ color: "var(--ink-2)", fontSize: 14, maxWidth: 820 }}>
        A shared workbook argues the strategy wins because 13 hand-picked large caps stayed inside ±12% of
        month-open in <b style={{ color: "var(--ink)" }}>74.2%</b> of the last 79 months. We agree — and went one step further:
        we sold an actual strangle on <i>every one</i> of those 13 stocks, <i>every</i> tradeable month of the judged window,
        with real premiums and real costs ({study.forced_stats.n_trades} trades).
      </p>
      <div style={{ display: "flex", gap: 28, flexWrap: "wrap", margin: "10px 0 14px" }}>
        {[["Win rate", `${(study.forced_stats.win_rate * 100).toFixed(1)}%`, "var(--buy)", "even higher than his sheet claims"],
          ["Profit factor", study.forced_stats.profit_factor.toFixed(2), "var(--hold)", "₹1.03 won per ₹1.00 lost"],
          ["Total return (3.6y)", `${(study.forced_stats.total_return * 100).toFixed(1)}%`, "var(--sell)", "an FD made ~25% in the same period"],
          ["His rules only (score ≥75)", `${(study.rules_stats.total_return * 100).toFixed(1)}%`, "var(--sell)", `${study.rules_stats.n_trades} trades, ${(study.rules_stats.win_rate * 100).toFixed(0)}% wins`],
        ].map(([label, value, tone, note]) => (
          <div key={label}>
            <div className="t-eyebrow">{label}</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 24, color: tone }}>{value}</div>
            <div style={{ color: "var(--faint)", fontSize: 11 }}>{note}</div>
          </div>
        ))}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, fontFamily: "var(--font-mono)" }}>
          <thead><tr>
            {["Stock", "Sheet: months inside ±12%", "Sim: trades", "Sim: win rate", "Sim: net P&L"].map(header => (
              <th key={header} style={{ textAlign: "left", padding: "6px 12px 6px 0", color: "var(--muted)", fontWeight: 400, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" }}>{header}</th>
            ))}
          </tr></thead>
          <tbody>
            {study.per_stock.map(row => (
              <tr key={row.symbol} style={{ borderTop: "1px solid var(--line)" }}>
                <td style={{ padding: "7px 12px 7px 0", color: "var(--ink-2)" }}>{row.symbol}</td>
                <td style={{ padding: "7px 12px 7px 0" }}>{(row.sheet_win_pct * 100).toFixed(0)}%</td>
                <td style={{ padding: "7px 12px 7px 0" }}>{row.sim_trades}</td>
                <td style={{ padding: "7px 12px 7px 0" }}>{row.sim_win_pct != null ? `${(row.sim_win_pct * 100).toFixed(0)}%` : "—"}</td>
                <td style={{ padding: "7px 12px 7px 0", color: row.sim_net_pnl >= 0 ? "var(--buy)" : "var(--sell)" }}>{money(row.sim_net_pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 12 }}>
        The spreadsheet measures how OFTEN the fence holds; it has no column for the price of the insurance or the size
        of the failures. With real option prices: 6 of the 13 stocks lose money outright, and the winners' rent barely
        clears costs. Win frequency was never in dispute — win economics was. Browse each stock's trades below.
      </p>
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

function diagnoseTrade(trade) {
  const money = (value) => `₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;
  const spotMovePct = trade.exit_spot && trade.entry_spot
    ? ((trade.exit_spot - trade.entry_spot) / trade.entry_spot * 100) : null;
  const moveText = spotMovePct == null ? "" :
    `The stock ${spotMovePct >= 0 ? "rose" : "fell"} ${Math.abs(spotMovePct).toFixed(1)}% over the trade (₹${trade.entry_spot?.toLocaleString("en-IN")} → ₹${trade.exit_spot?.toLocaleString("en-IN")}). `;
  const callBlowup = trade.exit_call_per_share / Math.max(trade.entry_call_per_share, 0.01);
  const putBlowup = trade.exit_put_per_share / Math.max(trade.entry_put_per_share, 0.01);
  const won = trade.net_pnl > 0;

  if (won && trade.exit_reason === "target") {
    return { tone: "var(--buy)", title: "Why it won",
      text: moveText + "It stayed comfortably inside the fence, so both promises lost value day after day (time decay). We bought them back at 20% of what we sold them for and pocketed the difference — the exact quiet month the strategy is built for. Note the size of the win though: " + money(trade.net_pnl) + " on " + money(trade.margin) + " blocked for weeks." };
  }
  if (won && trade.exit_reason === "time") {
    return { tone: "var(--buy)", title: "Why it won (barely)",
      text: moveText + "The stock behaved, but premiums decayed too slowly to hit the 80% target, so the last-Tuesday square-off closed it with partial rent. Wins like this are the strategy's ceiling — small, slow, and capped." };
  }
  if (trade.breached) {
    const side = callBlowup > putBlowup ? "call" : "put";
    const blowup = Math.max(callBlowup, putBlowup);
    const entry_leg = side === "call" ? trade.entry_call_per_share : trade.entry_put_per_share;
    const exit_leg = side === "call" ? trade.exit_call_per_share : trade.exit_put_per_share;
    return { tone: "var(--sell)", title: "Why it lost — the fence failed",
      text: moveText + `That's straight through the sold ${side} strike — the ±10% "fence" the doc calls safe. The ${side} we sold for ₹${entry_leg?.toFixed(2)}/share ballooned to ₹${exit_leg?.toFixed(2)} (${blowup.toFixed(0)}×), and buying it back cost far more than all the rent collected. This is THE failure mode of option selling: the doc's rules (calm stock, RSI, sigma bands, score ${trade.score?.toFixed(0)}/100) all approved this trade — none of them can see a gap coming.` };
  }
  return { tone: "var(--sell)", title: "Why it lost",
    text: moveText + "The stock never actually crossed the fence — but it drifted close enough (or volatility rose enough) that the promises got MORE expensive instead of decaying. The square-off deadline arrived with buy-back prices above what we collected. You can lose without the fence breaking; premium prices move on fear, not just on price." };
}

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
      {(() => {
        const diagnosis = diagnoseTrade(trade);
        return (
          <div style={{ marginTop: 10, padding: "10px 14px", borderLeft: `3px solid ${diagnosis.tone}`, background: "var(--surface-2)", borderRadius: "0 8px 8px 0" }}>
            <div style={{ color: diagnosis.tone, fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>{diagnosis.title}</div>
            <div style={{ color: "var(--ink-2)", fontSize: 13 }}>{diagnosis.text}</div>
          </div>
        );
      })()}
    </div>
  );
}

function StockExplorer() {
  const data = window.OPTIONS_DATA;
  const [dataset, setDataset] = React.useState("portfolio");
  const tradesBySymbol = !data ? {} :
    (dataset === "sheet" && data.sheet_study
      ? data.sheet_study.trades_by_symbol : data.trades_by_symbol);
  const symbols = Object.keys(tradesBySymbol).sort();
  const [selectedSymbol, setSelectedSymbol] = React.useState(symbols[0] || "");
  if (!data) return null;
  const activeSymbol = tradesBySymbol[selectedSymbol] ? selectedSymbol : symbols[0];
  const symbolTrades = tradesBySymbol[activeSymbol] || [];
  const symbolNet = symbolTrades.reduce((sum, t) => sum + t.net_pnl, 0);
  const datasetButton = (key, label) => (
    <button onClick={() => setDataset(key)}
            style={{ background: dataset === key ? "var(--accent)" : "var(--surface-2)",
                     color: dataset === key ? "var(--accent-ink)" : "var(--ink-2)",
                     border: "1px solid var(--line-strong)", borderRadius: "var(--radius-pill)",
                     padding: "6px 14px", fontSize: 12, cursor: "pointer" }}>{label}</button>
  );
  return (
    <div className="card" style={{ background: "var(--surface)" }}>
      <span className="t-eyebrow">Walk through the simulation, stock by stock</span>
      <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 12 }}>
        Every simulated trade (2023 → Aug 2026), reconstructed step by step against the doc's rules. Choose a dataset, then a stock:
      </p>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        {datasetButton("portfolio", "The judged portfolio run (his full rules)")}
        {data.sheet_study && datasetButton("sheet", "His 13 spreadsheet stocks (every tradeable month)")}
      </div>
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <select value={activeSymbol} onChange={e => setSelectedSymbol(e.target.value)}
                style={{ background: "var(--surface-2)", color: "var(--ink)", border: "1px solid var(--line-strong)", borderRadius: 8, padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 14 }}>
          {symbols.map(symbol => {
            const net = tradesBySymbol[symbol].reduce((sum, t) => sum + t.net_pnl, 0);
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
      <SectionHeader number="01" title="The idea"
        sub="The strategy from the shared notes, in plain words." />
      <IdeaCard />

      <SectionHeader number="02" title="What we did"
        sub="How the idea was put on trial — honestly, with real data and real costs." />
      <WhatWeDidCard />

      <SectionHeader number="03" title="What 43 months of data said"
        sub="The verdict, the numbers behind it, and the doc's key rules put to the test." />
      <VerdictBanner />
      <StatRow />
      <CriteriaCard />
      <ComparisonCard
        title='"Just trade the top-20 hippo stocks" — tested'
        intro={findings.top20.intro}
        header={["Metric", "Full F&O universe", "Top-20 only"]}
        rows={findings.top20.rows}
        why={findings.top20.why} />
      <SheetStudyCard />
      <ComparisonCard
        title="Stop-losses made everything worse"
        intro={findings.stops.intro}
        header={["Variant", "Total (2019–22)", "Sharpe"]}
        rows={findings.stops.rows}
        why={findings.stops.why} />
      <AttributionCard />

      <SectionHeader number="04" title="See it yourself — pick a stock"
        sub="Every trade the simulation took, reconstructed step by step, each with a plain-words diagnosis of why it won or lost." />
      <StockExplorer />

      <SectionHeader number="05" title="Appendix"
        sub="Definitions, the doc audited line by line, and the fine print." />
      <GlossaryCard />
      <DocAudit />
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
