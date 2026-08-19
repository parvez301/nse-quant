/* global React */
/* OPTIONS tab — the clean-26 strangle study, live.
   Four sections: what we wanted, what we did, what we excluded, and deep
   per-stock navigation for the 26 large caps. All data comes from
   /api/options/clean-tracker (recomputed nightly at 21:30 IST). */

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

function WantedCard() {
  return (
    <div className="card">
      <p style={{ color: "var(--ink-2)", fontSize: 14, maxWidth: 820 }}>
        Test one question with real data: can selling monthly <b style={{ color: "var(--ink)" }}>strangles</b> —
        collecting an upfront fee for promising a big stock won't move more than ~10% in a month, on both the up
        and down side — earn steady income on India's largest companies? Starting capital{" "}
        <b style={{ color: "var(--ink)" }}>₹10,00,000</b>, only the calmest conditions: big liquid stocks, no
        event-heavy months, take profit early, never ride a position into expiry.
      </p>
    </div>
  );
}

function DidCard() {
  const steps = [
    ["Real market data, real costs",
     "Every NSE stock-option's official end-of-day price for the trailing 24 months. Every simulated trade pays full retail costs: brokerage, STT, exchange charges, GST, stamp duty, and slippage (doubled on stressed exits)."],
    ["Fixed mechanical rules — no hindsight",
     "Each tradeable month: sell one call ~10% above and one put ~10% below the stock's price (delta ≈ 0.15). Buy both back once 80% of the fee is earned, or square off on the last Tuesday before expiry. No discretion, no adjustments."],
    ["26 large caps, two portfolio modes",
     "The 20 largest F&O stocks plus 6 more large caps (26 total). Mode A: a quality score picks only the best setups (max 3 at a time). Mode B: every stock, every tradeable month, until the ₹10L margin is full."],
  ];
  return (
    <div className="card">
      {steps.map(([title, body], index) => (
        <div key={title} style={{ borderTop: index ? "1px solid var(--line)" : "none", padding: "10px 0" }}>
          <div style={{ color: "var(--ink)", fontSize: 14, marginBottom: 3 }}>{index + 1} · {title}</div>
          <div style={{ color: "var(--muted)", fontSize: 13, maxWidth: 840 }}>{body}</div>
        </div>
      ))}
    </div>
  );
}

function ExcludedCard({ tracker }) {
  const windowEvents = tracker.excluded_events.filter(event => event.in_window);
  const cycles = tracker.cycles;
  return (
    <div className="card">
      <p style={{ color: "var(--ink-2)", fontSize: 14, marginBottom: 12, maxWidth: 840 }}>
        No new positions were opened in any month touched by a major macro event or a quarterly-results season.
        In the last 24 months ({tracker.window.start} → {tracker.window.end}) that removed{" "}
        <b style={{ color: "var(--ink)" }}>{cycles.macro + cycles.earnings} of {cycles.total} monthly cycles</b> —
        the simulation traded in <b style={{ color: "var(--accent)" }}>{cycles.clean}</b>.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 24 }}>
        <div>
          <div className="t-eyebrow" style={{ marginBottom: 8 }}>Macro events excluded ({cycles.macro} cycles)</div>
          {windowEvents.map(event => (
            <div key={event.start} style={{ display: "flex", justifyContent: "space-between", gap: 12, borderTop: "1px solid var(--line)", padding: "6px 0", fontSize: 13 }}>
              <span style={{ color: "var(--ink-2)" }}>{event.reason}</span>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--faint)", flex: "none", fontSize: 12 }}>{event.start} → {event.end}</span>
            </div>
          ))}
        </div>
        <div>
          <div className="t-eyebrow" style={{ marginBottom: 8 }}>Results seasons excluded ({cycles.earnings} cycles)</div>
          <div style={{ color: "var(--ink-2)", fontSize: 13 }}>
            Every month overlapping a quarterly-results window — 7 to 45 days after each quarter end
            (Mar 31, Jun 30, Sep 30, Dec 31), per SEBI's reporting deadline. Stocks move hardest on their own
            results; those months never trade.
          </div>
          <div style={{ marginTop: 14, fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--muted)" }}>
            24 cycles − {cycles.macro} macro − {cycles.earnings} results = <span style={{ color: "var(--accent)" }}>{cycles.clean} traded</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ResultsStrip({ tracker }) {
  const money = (value) => `${value < 0 ? "−" : "+"}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;
  const tiles = [
    ["Mode A · best setups only", tracker.rules_final_equity,
     `${tracker.rules_stats.n_trades} trades · ${((tracker.rules_stats.win_rate || 0) * 100).toFixed(0)}% ended in profit`],
    ["Mode B · every stock, every month", tracker.fill_final_equity,
     `${tracker.fill_stats.n_trades} trades · ${((tracker.fill_stats.win_rate || 0) * 100).toFixed(0)}% ended in profit`],
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 260px), 1fr))", gap: "var(--gap)" }}>
      {tiles.map(([label, equity, note]) => (
        <div className="card" key={label} style={{ padding: 18 }}>
          <span className="t-eyebrow">{label}</span>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 26, color: equity >= tracker.capital ? "var(--buy)" : "var(--sell)" }}>
            ₹{equity.toLocaleString("en-IN")}
          </div>
          <div style={{ color: "var(--faint)", fontSize: 12 }}>
            from ₹{tracker.capital.toLocaleString("en-IN")} ({money(equity - tracker.capital)}) · {note}
          </div>
        </div>
      ))}
      <div className="card" style={{ padding: 18 }}>
        <span className="t-eyebrow">Updated</span>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 16, color: "var(--ink)" }}>{tracker.generated_at_utc}</div>
        <div style={{ color: "var(--faint)", fontSize: 12 }}>
          data through {tracker.last_archive_day} · recomputed nightly 21:30 IST after NSE publishes
        </div>
      </div>
    </div>
  );
}

/* ── Per-trade walkthrough (unchanged mechanics) ────────────────── */
const EXIT_NARRATIVE = {
  target: 'Rule fired: "exit once 80% of the fee is earned." Premium decayed — bought both legs back cheap.',
  time:   'Rule fired: "square off last Tuesday before expiry." The profit target never arrived.',
  stop:   "Stop-loss fired — bought back in a stressed market (double slippage charged).",
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
      text: moveText + "It stayed comfortably inside the fence, so both promises lost value day after day (time decay). We bought them back at 20% of what we sold them for and pocketed the difference — the quiet month this strategy is built for. Note the size: " + money(trade.net_pnl) + " on " + money(trade.margin) + " blocked for weeks." };
  }
  if (won && trade.exit_reason === "time") {
    return { tone: "var(--buy)", title: "Why it won (barely)",
      text: moveText + "The stock behaved, but premiums decayed too slowly to hit the 80% target, so the last-Tuesday square-off closed it with partial rent. Wins like this are the ceiling — small, slow, capped." };
  }
  if (trade.breached) {
    const side = callBlowup > putBlowup ? "call" : "put";
    const blowup = Math.max(callBlowup, putBlowup);
    const entry_leg = side === "call" ? trade.entry_call_per_share : trade.entry_put_per_share;
    const exit_leg = side === "call" ? trade.exit_call_per_share : trade.exit_put_per_share;
    return { tone: "var(--sell)", title: "Why it lost — the fence failed",
      text: moveText + `That's straight through the sold ${side} strike — the ±10% "fence". The ${side} sold for ₹${entry_leg?.toFixed(2)}/share ballooned to ₹${exit_leg?.toFixed(2)} (${blowup.toFixed(0)}×); buying it back cost far more than all the fees collected. This is THE failure mode of option selling — and it happened in a month with no scheduled events at all. Gaps don't check the calendar.` };
  }
  return { tone: "var(--sell)", title: "Why it lost",
    text: moveText + "The stock never crossed the fence — but it drifted close enough (or volatility rose enough) that the promises got MORE expensive instead of decaying. The square-off arrived with buy-back prices above what was collected. You can lose without the fence breaking; premiums move on fear, not just price." };
}

function TradeWalkthrough({ trade, index, forceOpen }) {
  const [isOpen, setIsOpen] = React.useState(forceOpen === true || index === 0);
  const distancePct = (strike) => (Math.abs(strike - trade.entry_spot) / trade.entry_spot * 100).toFixed(1);
  const pnlColor = trade.net_pnl >= 0 ? "var(--buy)" : "var(--sell)";
  const money = (value) => `₹${Math.round(value).toLocaleString("en-IN")}`;
  const diagnosis = diagnoseTrade(trade);
  const step = (label, body) => (
    <div className="walk-step">
      <span className="t-eyebrow" style={{ paddingTop: 2 }}>{label}</span>
      <div style={{ fontSize: 13, color: "var(--ink-2)" }}>{body}</div>
    </div>
  );
  return (
    <div className="card" style={{ padding: "12px 18px" }}>
      <button className="trade-acc-head" data-open={isOpen} onClick={() => setIsOpen(!isOpen)} aria-expanded={isOpen}>
        <span className="chev">▶</span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}>
          #{index + 1} · {trade.entry_date} → {trade.exit_date}
        </span>
        <span className="exit-chip" data-kind={trade.exit_reason}>{trade.exit_reason}</span>
        {trade.breached && <span style={{ color: "var(--sell)", fontSize: 11 }}>⚠ fence broken</span>}
        <span style={{ color: diagnosis.tone, fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {diagnosis.title}
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 15, color: pnlColor, marginLeft: "auto", flex: "none" }}>
          {trade.net_pnl >= 0 ? "+" : ""}{money(trade.net_pnl)}
        </span>
      </button>
      {isOpen && <div>
      {step("1 · Entry", <>
        Entered {trade.entry_date} at closing prices, first Friday of the monthly cycle.
        Spot <b style={{ color: "var(--ink)" }}>₹{trade.entry_spot?.toLocaleString("en-IN")}</b>
        {trade.rsi_at_entry != null && <> · RSI(14) <b style={{ color: "var(--ink)" }}>{trade.rsi_at_entry.toFixed(0)}</b> (45–55 = calm)</>}
        {" "}· setup score {trade.score?.toFixed(0)}/100 · band grade <b style={{ color: "var(--ink)" }}>{trade.grade}</b>
      </>)}
      {step("2 · Strikes", <>
        Sold CALL <b style={{ color: "var(--ink)" }}>{trade.call_strike}</b> ({distancePct(trade.call_strike)}% above, delta {trade.call_delta?.toFixed(3)}, IV {(trade.call_iv * 100).toFixed(0)}%)
        {" "}+ PUT <b style={{ color: "var(--ink)" }}>{trade.put_strike}</b> ({distancePct(trade.put_strike)}% below, delta {trade.put_delta?.toFixed(3)}, IV {(trade.put_iv * 100).toFixed(0)}%).
      </>)}
      {step("3 · Premium", <>
        Collected <b style={{ color: "var(--buy)" }}>{money(trade.premium_collected)}</b> ({trade.entry_premium_per_share?.toFixed(2)}/share × lot {trade.lot_size}),
        paying {money(trade.entry_costs)} entry costs. Exchange blocked <b style={{ color: "var(--ink)" }}>{money(trade.margin)}</b> margin.
      </>)}
      {step("4 · Outcome", <>
        {EXIT_NARRATIVE[trade.exit_reason]}
        {" "}Bought back at {trade.exit_premium_per_share?.toFixed(2)}/share on {trade.exit_date} (exit costs {money(trade.exit_costs)}).
        {trade.breached && <b style={{ color: "var(--sell)" }}> ⚠ The ±10% fence FAILED on this trade.</b>}
      </>)}
      {step("5 · Net", <>
        Gross {money(trade.gross_pnl)} − costs {money(trade.entry_costs + trade.exit_costs)} =
        <b style={{ color: pnlColor }}> {money(trade.net_pnl)}</b> on {money(trade.margin)} blocked
        {" "}(<b style={{ color: pnlColor }}>{(trade.net_pnl / trade.margin * 100).toFixed(1)}%</b> on margin for the cycle).
      </>)}
      <div style={{ margin: "10px 0 6px", padding: "10px 14px", borderLeft: `3px solid ${diagnosis.tone}`, background: "var(--surface-2)", borderRadius: "0 8px 8px 0" }}>
        <div style={{ color: diagnosis.tone, fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>{diagnosis.title}</div>
        <div style={{ color: "var(--ink-2)", fontSize: 13 }}>{diagnosis.text}</div>
      </div>
      </div>}
    </div>
  );
}

function ReportView({ rows }) {
  const money = (value) => `${value < 0 ? "−" : "+"}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <p style={{ color: "var(--muted)", fontSize: 13, margin: "4px 0 8px", maxWidth: 840 }}>
        Every stock, every trade, fully expanded — ordered worst to best. The entry thinking is the same
        checklist each time: clean month → calm RSI → strikes near 0.15 delta, ≥8% away, outside the
        expected-move band → score /100 → sell both legs, then only the three exit rules matter.
      </p>
      {rows.map(row => {
        const wins = row.trades.filter(t => t.net_pnl > 0).length;
        const breaches = row.trades.filter(t => t.breached).length;
        return (
          <div key={row.symbol} style={{ marginBottom: 18 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap", margin: "14px 0 8px", borderBottom: "1px solid var(--line-strong)", paddingBottom: 6 }}>
              <span className="t-display" style={{ fontSize: 22 }}>{row.symbol}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 14, color: row.net >= 0 ? "var(--buy)" : "var(--sell)" }}>{money(row.net)}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--muted)" }}>
                {row.trades.length} trades · {wins}W/{row.trades.length - wins}L{breaches > 0 && <> · <span style={{ color: "var(--sell)" }}>fence broke {breaches}×</span></>}
              </span>
            </div>
            {row.trades.length === 0 &&
              <div style={{ color: "var(--muted)", fontSize: 13 }}>No tradeable setup passed the filters in the window.</div>}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {row.trades.map((trade, index) => (
                <TradeWalkthrough key={trade.entry_date + index} trade={trade} index={index} forceOpen={true} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StockExplorer({ tracker }) {
  const tradesBySymbol = tracker.trades_by_symbol || {};
  const rows = tracker.universe.map(symbol => {
    const trades = tradesBySymbol[symbol] || [];
    return { symbol, trades, net: trades.reduce((sum, t) => sum + t.net_pnl, 0) };
  }).sort((a, b) => a.net - b.net);  // worst first — the losses lead the story
  const [selectedSymbol, setSelectedSymbol] = React.useState(null);
  const [viewMode, setViewMode] = React.useState("chart");
  const maxLoss = Math.max(1, ...rows.map(r => Math.max(0, -r.net)));
  const maxGain = Math.max(1, ...rows.map(r => Math.max(0, r.net)));
  const zeroPct = maxLoss / (maxLoss + maxGain) * 100;   // shared scale, one baseline
  const selectedRow = rows.find(r => r.symbol === selectedSymbol) || null;
  const money = (value) => `${value < 0 ? "−" : "+"}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;
  React.useEffect(() => {
    if (!selectedRow) return;
    const onKey = (event) => { if (event.key === "Escape") setSelectedSymbol(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedRow]);
  return (
    <div className="card" style={{ background: "var(--surface)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <span className="t-eyebrow">All 26 at a glance — click a row for its trades, step by step</span>
        <button onClick={() => setViewMode(viewMode === "chart" ? "report" : "chart")}
                style={{ marginLeft: "auto", background: viewMode === "report" ? "var(--accent)" : "var(--surface-2)",
                         color: viewMode === "report" ? "var(--accent-ink)" : "var(--ink-2)",
                         border: "1px solid var(--line-strong)", borderRadius: "var(--radius-pill)",
                         padding: "6px 14px", fontSize: 12, cursor: "pointer" }}>
          {viewMode === "chart" ? "Read the full report — all 26, every trade" : "Back to the chart"}
        </button>
      </div>
      <p style={{ color: "var(--muted)", fontSize: 12, margin: "6px 0 12px" }}>
        Study view: each stock simulated independently in every clean month.
        (The ₹10L portfolio above holds ~6 positions at a time — its trades are a subset of these.)
        Dots are that stock's trades in order: <span style={{ color: "var(--buy)" }}>●</span> profit ·{" "}
        <span style={{ color: "var(--sell)" }}>●</span> loss · ○ ring = the ±10% fence broke.
      </p>
      {viewMode === "report" && <ReportView rows={rows} />}
      {viewMode === "chart" && <>
      <div role="listbox" aria-label="Stocks ranked by net P&L">
        {rows.map(row => {
          const isSelected = row.symbol === selectedSymbol;
          const barLeftPct = row.net < 0 ? zeroPct - (-row.net / maxLoss) * zeroPct : zeroPct;
          const barWidthPct = row.net < 0 ? (-row.net / maxLoss) * zeroPct
                                          : (row.net / maxGain) * (100 - zeroPct);
          return (
            <button key={row.symbol} role="option" aria-selected={isSelected}
                    onClick={() => setSelectedSymbol(isSelected ? null : row.symbol)}
                    className="stock-row" data-selected={isSelected}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, color: isSelected ? "var(--ink)" : "var(--ink-2)", textAlign: "left" }}>{row.symbol}</span>
              <span className="stock-dots" aria-hidden="true">
                {row.trades.map((trade, index) => (
                  <span key={index} title={`${trade.entry_date} → ${trade.exit_date} · ${money(trade.net_pnl)} · ${trade.exit_reason}${trade.breached ? " · fence broken" : ""}`}
                        style={{
                          width: 9, height: 9, borderRadius: "50%", display: "inline-block",
                          background: trade.net_pnl > 0 ? "var(--buy)" : "var(--sell)",
                          boxShadow: trade.breached ? "0 0 0 2px var(--surface), 0 0 0 3.5px var(--sell)" : "none",
                        }} />
                ))}
              </span>
              <span className="stock-bar-track" aria-hidden="true">
                <span style={{ position: "absolute", left: `${zeroPct}%`, top: 0, bottom: 0, width: 1, background: "var(--line-strong)" }} />
                <span style={{
                  position: "absolute", top: 3, bottom: 3,
                  left: `${barLeftPct}%`, width: `${Math.max(barWidthPct, 0.4)}%`,
                  background: row.net < 0 ? "var(--sell)" : "var(--buy)",
                  borderRadius: row.net < 0 ? "4px 0 0 4px" : "0 4px 4px 0",
                  opacity: isSelected ? 1 : 0.75,
                }} />
              </span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, textAlign: "right", color: row.net < 0 ? "var(--sell)" : "var(--buy)" }}>
                {money(row.net)}
              </span>
            </button>
          );
        })}
      </div>
      {selectedRow && <>
        <div className="trade-drawer-backdrop" onClick={() => setSelectedSymbol(null)} />
        <aside className="trade-drawer" role="dialog" aria-label={`${selectedRow.symbol} trades`}>
          <div className="trade-drawer-head">
            <span className="t-display" style={{ fontSize: 24 }}>{selectedRow.symbol}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--muted)" }}>
              {selectedRow.trades.length} trade{selectedRow.trades.length !== 1 ? "s" : ""}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 15, color: selectedRow.net >= 0 ? "var(--buy)" : "var(--sell)" }}>
              net {money(selectedRow.net)}
            </span>
            <button className="trade-drawer-close" onClick={() => setSelectedSymbol(null)}>Close · esc</button>
          </div>
          {selectedRow.trades.length === 0 &&
            <div style={{ color: "var(--muted)", fontSize: 13 }}>No tradeable setup passed the filters for this stock in the window.</div>}
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {selectedRow.trades.map((trade, index) => <TradeWalkthrough key={trade.entry_date + index} trade={trade} index={index} />)}
          </div>
        </aside>
      </>}
      </>}
    </div>
  );
}

function useIsPhone() {
  if (window.location.search.includes("phone=1")) return true;
  const query = "(max-width: 600px)";
  const [isPhone, setIsPhone] = React.useState(() => window.matchMedia(query).matches);
  React.useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (event) => setIsPhone(event.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return isPhone;
}

function CollapsedSection({ number, title, children }) {
  return (
    <details className="opt-fold">
      <summary>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent)", marginRight: 10 }}>{number}</span>
        <span className="t-display" style={{ fontSize: 19 }}>{title}</span>
        <span className="chev" aria-hidden="true">▶</span>
      </summary>
      <div style={{ paddingTop: 10 }}>{children}</div>
    </details>
  );
}

/* ── "What if I only trade the green ones?" — the winners trap ──── */
function WinnersTrapCard() {
  const rewindRows = [
    ["BAJFINANCE", "+₹15,889", "−₹90,096", "became the worst stock of the study"],
    ["HCLTECH", "+₹9,883", "+₹12,196", "the only one that stayed calm"],
    ["INFY", "+₹9,879", "+₹243", "one gap ate a year of rent"],
    ["AXISBANK", "+₹8,723", "−₹66,289", "two gaps — one was a RALLY"],
  ];
  return (
    <div className="card">
      <span className="t-eyebrow">The obvious next idea — "just keep the green ones" — tested</span>
      <p style={{ color: "var(--ink-2)", fontSize: 14, maxWidth: 840, margin: "8px 0 4px" }}>
        Looking at the chart above, everyone has the same thought: <i>drop the red stocks, sell options only
        on the winners.</i> Before acting on it, ask why those stocks are green. Not because they're a special
        kind of company — because <b style={{ color: "var(--ink)" }}>no big move happened to them in these
        particular months</b>. Rent has a ceiling (~₹3,000/month per stock) and gaps have no floor, so with a
        ~21% chance of a fence break per trade, plain dice predict ~5 of 26 stocks will finish green by luck
        alone. The green rows are the lottery's survivor list, not a strategy.
      </p>
      <p style={{ color: "var(--ink-2)", fontSize: 14, maxWidth: 840, margin: "8px 0 10px" }}>
        <b style={{ color: "var(--ink)" }}>We tested the idea anyway — by rewinding the tape.</b> Stand at
        July 2025, halfway through this study, see only the first year's ranking, and pick the four winners
        so far (by this exact rule). Then watch their <i>actual</i> next twelve months — months that are
        already in our data:
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 13, fontFamily: "var(--font-mono)", minWidth: 480 }}>
          <thead><tr>
            {["Your pick (July 2025)", "First year", "Their NEXT year", ""].map(header => (
              <th key={header} style={{ textAlign: "left", padding: "6px 18px 6px 0", color: "var(--muted)", fontWeight: 400, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" }}>{header}</th>
            ))}
          </tr></thead>
          <tbody>
            {rewindRows.map(([symbol, before, after, note]) => (
              <tr key={symbol} style={{ borderTop: "1px solid var(--line)" }}>
                <td style={{ padding: "7px 18px 7px 0", color: "var(--ink-2)" }}>{symbol}</td>
                <td style={{ padding: "7px 18px 7px 0", color: "var(--buy)" }}>{before}</td>
                <td style={{ padding: "7px 18px 7px 0", color: after.startsWith("−") ? "var(--sell)" : "var(--buy)" }}>{after}</td>
                <td style={{ padding: "7px 0", color: "var(--faint)", fontFamily: "var(--font-sans)", fontSize: 12 }}>{note}</td>
              </tr>
            ))}
            <tr style={{ borderTop: "1px solid var(--line-strong)" }}>
              <td style={{ padding: "7px 18px 7px 0", color: "var(--ink)" }}>"the safe green ones"</td>
              <td style={{ padding: "7px 18px 7px 0", color: "var(--buy)" }}>+₹44,374</td>
              <td style={{ padding: "7px 18px 7px 0", color: "var(--sell)", fontWeight: 600 }}>−₹1,43,946</td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <p style={{ color: "var(--ink-2)", fontSize: 14, maxWidth: 840, margin: "12px 0 0" }}>
        The #1 pick — calmest history, highest setup scores (78/100, grade A on the day it entered) — became
        the worst stock of the entire study. And the half-time <i>losers</i> lost another ₹72k too: there is
        no safe subset, only whichever stock's gap arrives next. Even with a time machine — knowing today's
        final top-4 in advance — trading only them earns +₹67,711 over two years on ~₹4 lakh of margin:
        about <b style={{ color: "var(--ink)" }}>8.5% a year, versus 7% in a fixed deposit</b>, as the prize
        for literally predicting the future.
      </p>
      <p style={{ color: "var(--warn)", fontSize: 13, marginTop: 10 }}>
        In one line: green means "hasn't exploded yet" — and the market already prices that calm into thinner
        fees. Picking past winners buys smaller rent with the same size truck.
      </p>
    </div>
  );
}

function OptionsView() {
  const [tracker, setTracker] = React.useState(null);
  const [failed, setFailed] = React.useState(false);
  const isPhone = useIsPhone();
  React.useEffect(() => {
    fetch("/api/options/clean-tracker").then(r => r.json())
      .then(payload => (payload && payload.generated_at_utc) ? setTracker(payload) : setFailed(true))
      .catch(() => setFailed(true));
  }, []);
  if (failed) return <div style={{ padding: 40, color: "var(--warn)", fontFamily: "var(--font-mono)" }}>Tracker data unavailable — next nightly run will restore it.</div>;
  if (!tracker) return <div style={{ padding: 40, color: "var(--muted)", fontFamily: "var(--font-mono)" }}>Loading study…</div>;

  if (isPhone) {
    // Phones lead with the numbers and the field; the story folds below.
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)", padding: "0 var(--gap) var(--gap)" }}>
        <SectionHeader number="—" title="The 26 stocks"
          sub="₹10 lakh, 24 months, cleanest conditions. Tap a row for its trades." />
        <ResultsStrip tracker={tracker} />
        <StockExplorer tracker={tracker} />
        <WinnersTrapCard />
        <CollapsedSection number="01" title="What we wanted"><WantedCard /></CollapsedSection>
        <CollapsedSection number="02" title="What we did"><DidCard /></CollapsedSection>
        <CollapsedSection number="03" title="What we excluded — last 24 months"><ExcludedCard tracker={tracker} /></CollapsedSection>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)", padding: "0 var(--gap) var(--gap)" }}>
      <div className="idea-method-grid">
        <div>
          <SectionHeader number="01" title="What we wanted"
            sub="One question, tested with real market data." />
          <WantedCard />
        </div>
        <div>
          <SectionHeader number="02" title="What we did"
            sub="Mechanical rules, official prices, full retail costs." />
          <DidCard />
        </div>
      </div>

      <SectionHeader number="03" title="What we excluded — last 24 months"
        sub="Time ranges where no new positions were opened." />
      <ExcludedCard tracker={tracker} />

      <SectionHeader number="04" title="The 26 stocks"
        sub="Where ₹10 lakh stands, and every simulated trade in detail." />
      <ResultsStrip tracker={tracker} />
      <StockExplorer tracker={tracker} />
      <WinnersTrapCard />
    </div>
  );
}

window.OptionsView = OptionsView;
