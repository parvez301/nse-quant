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
          <p>We didn't invent these. The system uses an off-the-shelf feature set called <strong>Alpha158</strong> — published by Microsoft as part of the open-source <a href="https://github.com/microsoft/qlib" target="_blank" rel="noopener">Qlib</a> library and used widely in quant research since 2020. Standing on shoulders, not engineering from scratch — and that's a deliberate choice. Battle-tested features tend to overfit less than home-baked ones.</p>
          <p>Despite the scary number, the 158 are mostly simple math on price and volume history. The exact composition (from <code>qlib/contrib/data/loader.py::Alpha158DL.get_feature_config</code>):</p>
          <table className="live-table">
            <thead><tr><th>Block</th><th className="num">Count</th><th>What it is</th></tr></thead>
            <tbody>
              <tr><td><strong>KBAR</strong></td><td className="num">9</td><td>Candle morphology (body, shadows, body-to-range ratio). Hand-coded, no rolling window.</td></tr>
              <tr><td><strong>Price</strong></td><td className="num">4</td><td>Today's OPEN/HIGH/LOW/VWAP each ÷ today's CLOSE.</td></tr>
              <tr><td><strong>Rolling</strong></td><td className="num">145</td><td>29 operators × 5 windows [5, 10, 20, 30, 60 trading days].</td></tr>
              <tr><td><strong>Total</strong></td><td className="num">158</td><td></td></tr>
            </tbody>
          </table>
          <p>Every feature is pure time-series on a single stock. There are <strong>no cross-sectional features</strong> in Alpha158 — no NIFTY-relative beta, no rank-vs-universe at the feature layer. Cross-sectional behaviour comes from how the model is trained (daily rank-normalisation + a pairwise ranking loss), not from Alpha158 itself.</p>

          <h3 style={{ marginTop: 36 }}>KBAR — 9 features, candle morphology</h3>
          <p>Inspired by Japanese candlesticks, written as pure ratios so a tree model can split on them. All unit-less, all from today's bar only.</p>
          <table className="live-table">
            <thead><tr><th>Name</th><th>Formula</th><th>Reads as</th></tr></thead>
            <tbody>
              <tr><td><code>KMID</code></td><td><code>(close − open) / open</code></td><td>Body size as % of open. +ve = bullish candle.</td></tr>
              <tr><td><code>KLEN</code></td><td><code>(high − low) / open</code></td><td>Total range. Day's volatility proxy.</td></tr>
              <tr><td><code>KMID2</code></td><td><code>(close − open) / (high − low)</code></td><td>Body as fraction of range. ±1 = marubozu, 0 = doji.</td></tr>
              <tr><td><code>KUP, KUP2</code></td><td><code>(high − max(open, close))</code> / open or / range</td><td>Upper-shadow length. Big = rejection from above.</td></tr>
              <tr><td><code>KLOW, KLOW2</code></td><td><code>(min(open, close) − low)</code> / open or / range</td><td>Lower-shadow length. Big = buyer step-in.</td></tr>
              <tr><td><code>KSFT, KSFT2</code></td><td><code>(2·close − high − low)</code> / open or / range</td><td>Where close sits in the bar. &gt;0 = closed in upper half.</td></tr>
            </tbody>
          </table>
          <p>Detects pin bars, marubozus, dojis at extremes — all compressed into ±1-ish numbers that tree-splits can carve up.</p>

          <h3 style={{ marginTop: 36 }}>Price — 4 features, intraday-relative pricing</h3>
          <p><code>OPEN0</code>, <code>HIGH0</code>, <code>LOW0</code>, <code>VWAP0</code> — each is today's value ÷ today's close. Tells the model where today's close sits inside today's bar (overlaps with KSFT by design — trees benefit from collinear features).</p>
          <p><em>Note: yfinance doesn't supply VWAP, so we synthesise it as <code>(high + low + close) / 3</code> in the qlib binary dump. Fine for ranking.</em></p>

          <h3 style={{ marginTop: 36 }}>Rolling — 145 features, 29 operators × 5 windows</h3>
          <p>Windows are fixed at <strong>[5, 10, 20, 30, 60]</strong> trading days (~1 week, 2 weeks, 1 month, 6 weeks, 3 months). No hyperparameter fishing at the feature layer.</p>

          <h4 style={{ marginTop: 24 }}>Trend &amp; momentum (5 operators)</h4>
          <table className="live-table">
            <thead><tr><th>Op</th><th>Formula</th><th>Captures</th></tr></thead>
            <tbody>
              <tr><td><code>{'ROC{d}'}</code></td><td><code>Ref(close, d) / close</code></td><td>Rate of change. (Qlib uses past/today, so 0.9 means up 11%.)</td></tr>
              <tr><td><code>{'MA{d}'}</code></td><td><code>Mean(close, d) / close</code></td><td>SMA ÷ today. &lt;1 = price above MA (uptrend).</td></tr>
              <tr><td><code>{'BETA{d}'}</code></td><td><code>Slope(close, d) / close</code></td><td>Linear-trend slope.</td></tr>
              <tr><td><code>{'RSQR{d}'}</code></td><td><code>R²(close, d)</code></td><td>How clean the trend is (0–1). High = smooth, low = chop.</td></tr>
              <tr><td><code>{'RESI{d}'}</code></td><td><code>residual / close</code></td><td>How far today is off the trend line. Mean-reversion candidate.</td></tr>
            </tbody>
          </table>
          <p><em>These overlap deliberately. ROC = discrete momentum, MA = drift vs. average, BETA = slope, RSQR = is the slope trustworthy, RESI = is today an outlier vs. that trend.</em></p>

          <h4 style={{ marginTop: 24 }}>Levels &amp; position-in-range (6 operators)</h4>
          <table className="live-table">
            <thead><tr><th>Op</th><th>Formula</th><th>Captures</th></tr></thead>
            <tbody>
              <tr><td><code>{'MAX{d}'}</code></td><td><code>Max(high, d) / close</code></td><td>d-day high ÷ today. &lt;1 = at/above a new high.</td></tr>
              <tr><td><code>{'MIN{d}'}</code></td><td><code>Min(low, d) / close</code></td><td>d-day low ÷ today.</td></tr>
              <tr><td><code>{'QTLU{d}, QTLD{d}'}</code></td><td><code>Quantile(close, d, 0.8 / 0.2) / close</code></td><td>Robust versions of MAX/MIN.</td></tr>
              <tr><td><code>{'RANK{d}'}</code></td><td><code>Rank(close, d)</code></td><td>Percentile rank of today's close in last d closes (0–1).</td></tr>
              <tr><td><code>{'RSV{d}'}</code></td><td><code>(close − low_d) / (high_d − low_d)</code></td><td>Stochastic %K. 1 = at d-day high, 0 = at d-day low.</td></tr>
            </tbody>
          </table>

          <h4 style={{ marginTop: 24 }}>Aroon-style temporal position (3 operators)</h4>
          <table className="live-table">
            <thead><tr><th>Op</th><th>Formula</th><th>Captures</th></tr></thead>
            <tbody>
              <tr><td><code>{'IMAX{d}'}</code></td><td><code>IdxMax(high, d) / d</code></td><td>How recently the d-day high happened. Aroon-Up.</td></tr>
              <tr><td><code>{'IMIN{d}'}</code></td><td><code>IdxMin(low, d) / d</code></td><td>How recently the d-day low happened. Aroon-Down.</td></tr>
              <tr><td><code>{'IMXD{d}'}</code></td><td><code>(IdxMax − IdxMin) / d</code></td><td>Did the low come after the high? &gt;0 = downtrend momentum.</td></tr>
            </tbody>
          </table>

          <h4 style={{ marginTop: 24 }}>RSI-family (6 operators)</h4>
          <table className="live-table">
            <thead><tr><th>Op</th><th>Formula</th><th>Captures</th></tr></thead>
            <tbody>
              <tr><td><code>{'CNTP{d}'}</code></td><td>% of last d days that closed up</td><td>Up-day frequency.</td></tr>
              <tr><td><code>{'CNTN{d}'}</code></td><td>% of last d days that closed down</td><td>Down-day frequency.</td></tr>
              <tr><td><code>{'CNTD{d}'}</code></td><td><code>CNTP − CNTN</code></td><td>Net up-day balance.</td></tr>
              <tr><td><code>{'SUMP{d}'}</code></td><td><code>Σ gains / Σ |Δclose|</code></td><td>RSI by magnitude — gain share.</td></tr>
              <tr><td><code>{'SUMN{d}'}</code></td><td><code>Σ losses / Σ |Δclose|</code></td><td>RSI by magnitude — loss share. SUMP + SUMN = 1.</td></tr>
              <tr><td><code>{'SUMD{d}'}</code></td><td><code>SUMP − SUMN</code></td><td>Net signed magnitude (Chande Momentum Oscillator).</td></tr>
            </tbody>
          </table>
          <p><em>CNT counts up days; SUM measures their size. A stock that "goes up small, down big" looks very different across the two — exactly the asymmetry trees can exploit.</em></p>

          <h4 style={{ marginTop: 24 }}>Price-volume interaction (2 operators)</h4>
          <table className="live-table">
            <thead><tr><th>Op</th><th>Formula</th><th>Captures</th></tr></thead>
            <tbody>
              <tr><td><code>{'CORR{d}'}</code></td><td><code>Corr(close, log(volume+1), d)</code></td><td>"Is volume confirming price?" +ve = healthy advance; −ve = distribution.</td></tr>
              <tr><td><code>{'CORD{d}'}</code></td><td><code>Corr(returns, log volume-change, d)</code></td><td>Same idea on returns and volume changes — cleaner statistically.</td></tr>
            </tbody>
          </table>

          <h4 style={{ marginTop: 24 }}>Volume-only (6 operators)</h4>
          <table className="live-table">
            <thead><tr><th>Op</th><th>Formula</th><th>Captures</th></tr></thead>
            <tbody>
              <tr><td><code>{'VMA{d}'}</code></td><td><code>Mean(volume, d) / volume</code></td><td>Today's volume vs. d-day average.</td></tr>
              <tr><td><code>{'VSTD{d}'}</code></td><td><code>Std(volume, d) / volume</code></td><td>Volatility of volume.</td></tr>
              <tr><td><code>{'WVMA{d}'}</code></td><td><code>Std(|ret|·vol, d) / Mean(|ret|·vol, d)</code></td><td>How lumpy active money flow is. High = erratic / news-driven.</td></tr>
              <tr><td><code>{'VSUMP{d}, VSUMN{d}, VSUMD{d}'}</code></td><td>RSI framework on volume changes</td><td>Volume-RSI.</td></tr>
            </tbody>
          </table>

          <h4 style={{ marginTop: 24 }}>Volatility (1 operator)</h4>
          <p><code>{'STD{d}'}</code> = <code>Std(close, d) / close</code>. The single literal "stdev of returns" feature. Volatility effects also bleed into RSQR, RESI, and WVMA — but only STD is pure.</p>

          <h3 style={{ marginTop: 36 }}>The label (the thing being predicted)</h3>
          <p>Alpha158 is only the X. The y is <code>Ref(close, -2) / Ref(close, -1) − 1</code> — the <strong>next-day close-to-close return</strong>. No look-ahead leakage: at decision time T, only data through T is used, and the model predicts the return from T+1 to T+2.</p>
          <p>The LightGBM ranker is trained with <strong>CSRankNorm</strong> (cross-sectional rank-normalisation per day) and a pairwise ranking loss — <strong>this is where the cross-sectional behaviour actually lives</strong>. The model isn't learning <em>"buy when ROC5 &lt; 0.95"</em>; it's learning <em>"rank stocks by their feature vector, and reward orderings where the high-ranked names outperform the low-ranked ones that day."</em></p>

          <h3 style={{ marginTop: 36 }}>Why this set works in practice</h3>
          <ul>
            <li><strong>Deliberately redundant.</strong> Most engineers prune correlated features. Alpha158 does the opposite: throw 158 collinear features at a regularised gradient-booster and let split-gain pick the cleanest one. Trees don't suffer from multicollinearity the way regressions do.</li>
            <li><strong>Zero hyperparameters at the feature layer.</strong> Windows are fixed at [5, 10, 20, 30, 60]. No grid-searching window size on backtest data — the single biggest source of academic survivorship bias.</li>
            <li><strong>All ratios are scale-invariant.</strong> A feature trained on ₹100 stocks generalises to ₹2000 stocks. No level-dependence drift.</li>
          </ul>

          <h3 style={{ marginTop: 36 }}>What it cannot detect</h3>
          <ul>
            <li><strong>No fundamentals</strong> — P/E, earnings dates, growth, FII flows, delivery%. Blind to event-driven moves.</li>
            <li><strong>No microstructure</strong> — bid-ask spread, order-book imbalance, intraday VWAP deviation. Daily bars only.</li>
            <li><strong>No news or sentiment.</strong></li>
            <li><strong>No true cross-sectional features</strong> — no NIFTY-relative beta or sector-relative momentum at the feature layer. The ranker compensates partially; classical relative-strength (à la O'Neill / IBD) would need a custom handler.</li>
            <li><strong>Regime change.</strong> In low-vol regimes WVMA / STD dominate splits; in high-vol regimes ROC takes over. The model can be trained on the wrong regime mix.</li>
          </ul>

          <h3 style={{ marginTop: 36 }}>References</h3>
          <ul>
            <li>Feature definitions: <code>qlib/contrib/data/loader.py::Alpha158DL.get_feature_config</code></li>
            <li>Handler (loader + label + per-day normalisation): <code>qlib/contrib/data/handler.py::Alpha158</code></li>
            <li>Microsoft Qlib paper: <em>Qlib: An AI-oriented Quantitative Investment Platform</em>, arXiv:2009.11189 (the feature list itself is open-source-only, not in the paper).</li>
          </ul>

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
