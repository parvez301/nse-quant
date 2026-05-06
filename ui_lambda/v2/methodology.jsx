/* global React */
const { useState, useEffect } = React;

const fmtPctR = (n, d = 2) => n == null ? "—" : `${(n * 100).toFixed(d)}%`;
const fmtN = (n) => n == null ? "—" : Number(n).toLocaleString("en-IN");

const SECTIONS = [
  { id: "what", label: "What this is" },
  { id: "how",  label: "How it works" },
  { id: "ingredients", label: "The 158 features" },
  { id: "model", label: "The model" },
  { id: "backtest", label: "Backtest honesty" },
  { id: "lies", label: "Where this can lie to you" },
  { id: "fixes", label: "How we fix them" },
  { id: "stack", label: "Stack" },
];

function MethodologyTOC({ active }) {
  return (
    <aside className="toc">
      <span className="t-eyebrow">On this page</span>
      {SECTIONS.map(s => (
        <a key={s.id} href={`#${s.id}`} className={active === s.id ? "active" : ""}>{s.label}</a>
      ))}
    </aside>
  );
}

function StratifiedTable({ s }) {
  if (!s?.scenarios) return null;
  return (
    <div>
      <div className="t-eyebrow" style={{ marginBottom: 10 }}>Live · stratified excess returns</div>
      <table className="live-table">
        <thead><tr>
          <th>Scenario</th><th className="num">N</th>
          <th className="num">Mean</th><th className="num">Median</th>
          <th className="num">Win-rate</th><th className="num">t-stat</th>
        </tr></thead>
        <tbody>
          {s.scenarios.map(sc => (
            <tr key={sc.label}>
              <td>{sc.label}</td>
              <td className="num">{sc.n_windows}</td>
              <td className="num" style={{ color: sc.mean_excess > 0 ? "var(--buy)" : "var(--sell)" }}>{fmtPctR(sc.mean_excess)}</td>
              <td className="num">{fmtPctR(sc.median_excess)}</td>
              <td className="num">{fmtPctR(sc.win_rate, 0)}</td>
              <td className="num">{sc.t_stat?.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CostTable({ s }) {
  if (!s?.cells) return null;
  return (
    <div>
      <div className="t-eyebrow" style={{ marginBottom: 10 }}>Live · cost sensitivity</div>
      <table className="live-table">
        <thead><tr>
          <th className="num">AUM</th><th className="num">Bps</th>
          <th className="num">Excess ann.</th><th className="num">Sharpe</th>
          <th className="num">Max DD</th><th className="num">Total cost</th>
        </tr></thead>
        <tbody>
          {s.cells.map((c, i) => (
            <tr key={i}>
              <td className="num">₹{fmtN(c.capital_inr)}</td>
              <td className="num">{c.base_bps}</td>
              <td className="num" style={{ color: c.excess_ann_return > 0 ? "var(--buy)" : "var(--sell)" }}>{fmtPctR(c.excess_ann_return)}</td>
              <td className="num">{c.sharpe?.toFixed(2)}</td>
              <td className="num" style={{ color: "var(--sell)" }}>{fmtPctR(c.max_drawdown)}</td>
              <td className="num">{fmtPctR(c.total_cost_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MethodologyView({ state }) {
  const [active, setActive] = useState("what");
  useEffect(() => {
    const obs = new IntersectionObserver((entries) => {
      const visible = entries.filter(e => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]) setActive(visible[0].target.id);
    }, { rootMargin: "-20% 0px -60% 0px", threshold: 0 });
    SECTIONS.forEach(s => {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    });
    return () => obs.disconnect();
  }, []);

  return (
    <div className="page">
      <div className="methodology">
        <MethodologyTOC active={active} />
        <article className="prose">
          <h1>Methodology</h1>
          <p className="lede">
            A daily, fully systematic stock-ranking model for the Indian equity market. Every trading day at 08:00 IST, an automated job ranks ~750 NSE stocks and emits a small basket of buy/sell/hold decisions for a paper portfolio. <strong>Nothing here is live-traded.</strong> This dashboard is the audit log.
          </p>

          <h2 id="what">What this is</h2>
          <p>The goal is to share the actual day-to-day decisions and equity curve so people I trust can poke holes in the methodology, the costs, and the assumptions — before any real money goes near it.</p>

          <h2 id="how">How it actually works</h2>
          <p>Think of this as an automated stock-screener that wakes up every morning, looks at ~750 Indian companies, and ranks them from "most likely to outperform peers in the next few days" to "most likely to underperform" — purely based on patterns it learned from the last 15 years of trading data.</p>
          <ol>
            <li><strong>Refresh prices.</strong> Pull yesterday's close for ~750 NSE stocks (NIFTY 500 + Microcap 250).</li>
            <li><strong>Cook up "ingredients".</strong> Compute 158 numbers per stock describing its recent behaviour.</li>
            <li><strong>Score and rank.</strong> A pre-trained gradient-boosted ranker reads those 158 numbers per stock, outputs one score, sort 750 high to low.</li>
            <li><strong>Decide.</strong> Top ~30 → today's BUY list. Anything currently held that has dropped out of the top ~35 → SELL.</li>
          </ol>

          <h2 id="ingredients">The 158 ingredients</h2>
          <p>We didn't invent these. The system uses an off-the-shelf feature set called <strong>Alpha158</strong> — published by Microsoft as part of the open-source Qlib library. Battle-tested features tend to overfit less than home-baked ones.</p>
          <table className="live-table">
            <thead><tr><th>Flavour</th><th className="num">Count</th><th>Plain-English example</th></tr></thead>
            <tbody>
              <tr><td><strong>Momentum</strong></td><td className="num">~30</td><td>Total return over the last 5/10/20/30/60 days.</td></tr>
              <tr><td><strong>Mean-reversion</strong></td><td className="num">~30</td><td>Today's close ÷ 20-day average − 1.</td></tr>
              <tr><td><strong>Volatility</strong></td><td className="num">~20</td><td>Rolling stdev of daily returns over various windows.</td></tr>
              <tr><td><strong>Volume signals</strong></td><td className="num">~25</td><td>Today's volume vs. 20-day average.</td></tr>
              <tr><td><strong>Candle shape</strong></td><td className="num">~20</td><td>(close − open) ÷ (high − low).</td></tr>
              <tr><td><strong>Cross-stats</strong></td><td className="num">~30</td><td>Correlation with NIFTY; rank within universe.</td></tr>
            </tbody>
          </table>

          <h2 id="model">The model</h2>
          <ul>
            <li><strong>LightGBM</strong> gradient-boosted ranker. No deep learning. No GPU. Output is a per-stock score; rank is what matters.</li>
            <li>Trained on ~15 years of history (~2010–2024).</li>
            <li>Default daily output: top-30 names re-evaluated every 5 trading days, with a 5-name buffer before forced rotation.</li>
          </ul>

          <h2 id="backtest">How honest is the backtest?</h2>
          <table className="live-table">
            <tbody>
              <tr><td>Walk-forward windows</td><td className="num">8 annual</td></tr>
              <tr><td>Positive windows</td><td className="num">7 of 8</td></tr>
              <tr><td>t-stat vs zero (excess return)</td><td className="num">3.79</td></tr>
              <tr><td>Modelled trading cost</td><td className="num">15 bps buy + 25 bps sell</td></tr>
            </tbody>
          </table>

          <h2 id="lies">Where this can lie to you</h2>
          <div className="honesty-box">
            <div className="label">⚠ Read this part</div>
            <p><strong>Survivorship bias is partially corrected.</strong> A curated list of <strong>31 well-documented NSE collapses 2008-2024</strong> is layered on. The implied annualised drag is approximately <strong>+104 bps/yr</strong>. Assume the published t-stat carries a defensible but non-trivial residual upward bias.</p>
            <p><strong>Two years carry the headline.</strong> 2020 (+178%) and 2021 (+107%) are post-COVID dispersion in Indian small/mid-caps — a regime, not repeatable alpha. Honest forward expectation is <strong>+8% to +15% excess</strong>, not +30%.</p>
            <p><strong>The portfolio is paper, the strategy is theory.</strong> Things this never models: market impact above the universe's typical turnover, T+1 settlement quirks, broker outages on volatile mornings, and the fact that your real-world costs almost certainly aren't 15/25 bps.</p>
          </div>

          <h2 id="fixes">How we plan to address these</h2>
          <p>Honest caveats matter, but writing them down isn't the same as fixing them.</p>
          <h3>1. Closing the survivorship gap</h3>
          <ul>
            <li><span className="status-badge done">Done</span>Curated 31 NSE collapses 2008-2024 — DHFL, RCOM, JET, Kingfisher, Unitech, Amtek, Videocon, IL&amp;FS Engineering. Implied drag <strong>≈ +104 bps/yr</strong>.</li>
            <li><span className="status-badge now">In progress</span>ISIN-based corporate-action filtering — so SBIN→SBIN-RE renames don't register as delistings.</li>
            <li><span className="status-badge next">Planned</span>Pull the full NSE Bhavcopy archive back to ~2008 (~5,500 files). The real fix.</li>
            <li><span className="status-badge hard">Hard</span>Paid PIT data (Bloomberg / Refinitiv). Overkill for personal scale.</li>
          </ul>
          <StratifiedTable s={state.stratified} />

          <h3 style={{ marginTop: 36 }}>2. Removing regime dependence</h3>
          <ul>
            <li><span className="status-badge done">Done</span>Stratified results published — see live table above.</li>
            <li><span className="status-badge next">Planned</span>Retrain without 2020/21 data and rerun walk-forward.</li>
            <li><span className="status-badge next">Planned</span>Volatility scaling — reduce position sizing in high-VIX regimes.</li>
          </ul>

          <h3 style={{ marginTop: 36 }}>3. Closing the paper-vs-real gap</h3>
          <ul>
            <li><span className="status-badge done">Done</span>ADV-aware slippage model — cost sensitivity matrix below.</li>
            <li><span className="status-badge done">Done</span>T+1 settlement — sell proceeds sit in a pending-settlement ledger.</li>
            <li><span className="status-badge done">Done</span>Outage Monte Carlo — randomly skips rebalance days.</li>
            <li><span className="status-badge hard">Hard</span>Live execution. Months of work; deliberately not a near-term goal.</li>
          </ul>
          <CostTable s={state.costSensitivity} />

          <h2 id="stack">Stack</h2>
          <ul>
            <li>Data: <code>yfinance</code> → Qlib binary store</li>
            <li>Features: Qlib <code>Alpha158</code></li>
            <li>Model: <code>LightGBM</code> ranker</li>
            <li>Cron: AWS Fargate Spot (ARM64), scheduled by EventBridge</li>
            <li>State: S3 (one bucket; data + outputs + audit trail)</li>
            <li>This UI: a single Lambda + CloudFront</li>
          </ul>
        </article>
      </div>
    </div>
  );
}

window.MethodologyView = MethodologyView;
