/* global React, ReactDOM */

const { useState, useEffect, useMemo } = React;

// ─── Helpers ─────────────────────────────────────────────────────
const fmtINR = (n, d = 0) =>
  n == null ? "—" :
  Number(n).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmtPct = (n, d = 2) => n == null ? "—" : `${n >= 0 ? "+" : ""}${(n * 100).toFixed(d)}%`;
const fmtPctRaw = (n, d = 2) => n == null ? "—" : `${(n * 100).toFixed(d)}%`;
const fmtRsBig = (n) => n == null ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });

// Mini SVG sparkline drawing equity vs nifty (both normalised to 100 at start)
function Spark({ rows, height = 180 }) {
  if (!rows || rows.length === 0) return null;
  const eq = rows.map(r => +r.total_equity);
  const ni = rows.map(r => +r.nifty50_close);
  const eq0 = eq[0], ni0 = ni[0];
  const eqN = eq.map(v => v / eq0);
  const niN = ni.map(v => v / ni0);
  const all = [...eqN, ...niN, 1];
  const min = Math.min(...all), max = Math.max(...all);
  const pad = (max - min) * 0.12 || 0.005;
  const lo = min - pad, hi = max + pad;
  const W = 480, H = height;
  const x = i => (i / (rows.length - 1)) * (W - 2) + 1;
  const y = v => H - ((v - lo) / (hi - lo)) * (H - 8) - 4;

  const path = (arr) => arr.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = (arr) => `${path(arr)} L${x(arr.length - 1).toFixed(1)},${H} L${x(0).toFixed(1)},${H} Z`;

  // y for baseline (=1)
  const yBase = y(1);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: H }}>
      <defs>
        <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor="var(--accent)" stopOpacity="0.28"/>
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
        </linearGradient>
      </defs>
      <line x1="0" x2={W} y1={yBase} y2={yBase} stroke="var(--line)" strokeDasharray="2 4" />
      <path d={area(eqN)} fill="url(#eqfill)" />
      <path d={path(niN)} fill="none" stroke="var(--muted)" strokeWidth="1.25" strokeDasharray="3 3" />
      <path d={path(eqN)} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {/* legend */}
      <g fontFamily="var(--font-sans)" fontSize="11" fill="var(--muted)">
        <circle cx="10" cy="14" r="3" fill="var(--accent)" />
        <text x="18" y="17">Strategy</text>
        <line x1="78" y1="14" x2="92" y2="14" stroke="var(--muted)" strokeDasharray="3 3" />
        <text x="98" y="17">NIFTY 50</text>
      </g>
    </svg>
  );
}

// ─── Topbar ─────────────────────────────────────────────────────
function Topbar({ tab, setTab, lastRun, halt }) {
  return (
    <div className="topbar">
      <div className="brand">
        <div className="brand-mark" />
        <span className="brand-name">NSE Quant</span>
        <span className="brand-sub">/ daily review</span>
      </div>
      <div className="nav-tabs">
        <button className="nav-tab" data-active={tab === "today"} onClick={() => setTab("today")}>Today</button>
        <button className="nav-tab" data-active={tab === "dashboard"} onClick={() => setTab("dashboard")}>Portfolio</button>
        <button className="nav-tab" data-active={tab === "explorer"} onClick={() => setTab("explorer")}>Lab</button>
        <button className="nav-tab" data-active={tab === "methodology"} onClick={() => setTab("methodology")}>Method</button>
      </div>
      <div className="topbar-right">
        <span className="system-pill" data-state={halt?.halted ? "halt" : "ok"}>
          <span className="dot" />
          {halt?.halted ? "Halted" : "Live"}
          <span style={{ color: "var(--muted)", marginLeft: 4 }}>· {lastRun?.date}</span>
        </span>
        <button className="btn">Refresh</button>
      </div>
    </div>
  );
}

// ─── Trust strip ───────────────────────────────────────────────
function TrustStrip({ clock }) {
  if (!clock) return null;
  const n = clock.consecutive_clean_days || 0;
  const target = clock.target_days || 90;
  const pct = Math.min(100, (n / target) * 100);
  return (
    <div className="trust-strip">
      <span className="t-eyebrow">90-Day Paper-Trade Gate</span>
      <div className="trust-bar"><span style={{ width: `${pct}%` }} /></div>
      <div className="trust-meta" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
        <strong>Day {n}</strong> of {target} clean
        <span style={{ marginLeft: 14, color: "var(--faint)" }}>·</span>
        <span style={{ marginLeft: 14 }}>last reset {clock.last_reset_date}</span>
      </div>
    </div>
  );
}

// ─── Hero P&L ─────────────────────────────────────────────────
function Hero({ equity }) {
  if (!equity?.length) return null;
  const last = equity[equity.length - 1];
  const first = equity[0];
  const peak = Math.max(...equity.map(r => +r.total_equity));
  const totalRet = +last.total_equity / +first.total_equity - 1;
  const dailyRet = equity.length > 1 ? +last.total_equity / +equity[equity.length - 2].total_equity - 1 : 0;
  const dd = +last.total_equity / peak - 1;
  const niftyRet = +last.nifty50_close / +first.nifty50_close - 1;
  const alpha = totalRet - niftyRet;
  const earlyDays = equity.length < 60;

  return (
    <section className="hero">
      <div className="hero-pl">
        <div className="hero-pl-figure">
          <span className="t-eyebrow">Paper Equity</span>
          <div className="hero-amount">
            <span className="hero-rs">₹</span>{fmtRsBig(last.total_equity)}
          </div>
          <div className="hero-deltas">
            <div>
              <span>Today</span>
              <span className={`v ${dailyRet >= 0 ? "up" : "down"}`}>{fmtPct(dailyRet)}</span>
            </div>
            <div>
              <span>Since inception ({equity.length}d)</span>
              <span className={`v ${totalRet >= 0 ? "up" : "down"}`}>{fmtPct(totalRet)}</span>
            </div>
            <div>
              <span>Drawdown from peak</span>
              <span className={`v ${dd <= -0.05 ? "down" : ""}`} style={{ color: dd <= -0.05 ? "var(--sell)" : "var(--ink-2)" }}>{fmtPctRaw(dd)}</span>
            </div>
          </div>
        </div>
        <div className="hero-spark"><Spark rows={equity} /></div>
      </div>

      <div className="hero-alpha">
        <span className="t-eyebrow">Alpha vs NIFTY 50</span>
        <div className={`alpha-bignum ${alpha < 0 ? "down" : ""}`}>{fmtPct(alpha, 2)}</div>
        <div className="alpha-rows">
          <div className="alpha-row"><span className="k">Strategy</span><span className="v">{fmtPct(totalRet)}</span></div>
          <div className="alpha-row"><span className="k">NIFTY 50, same window</span><span className="v" style={{ color: "var(--muted)" }}>{fmtPct(niftyRet)}</span></div>
          <div className="alpha-row"><span className="k">Positions / Cash</span><span className="v">{last.n_positions} <span style={{ color: "var(--muted)" }}>/ ₹{fmtINR(last.cash)}</span></span></div>
        </div>
      </div>

      {earlyDays && (
        <div className="caveat-banner">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" />
          </svg>
          <span>
            <strong>Statistical caveat.</strong> Equity history has only <strong>{equity.length} days</strong> of cloud-cron data.
            These numbers carry too much variance to read as a verdict yet — wait until ~3 weeks before judging the strategy.
          </span>
        </div>
      )}
    </section>
  );
}

// ─── Today's actions board ────────────────────────────────────
function ActionsBoard({ decisions }) {
  if (!decisions?.length) return null;
  const today = decisions[0];
  const buy = today.actions?.BUY || [];
  const sell = today.actions?.SELL || [];
  const hold = today.actions?.HOLD || [];

  const buyMax = Math.max(0.001, ...buy.map(b => b.score || 0));
  const holdMax = Math.max(0.001, ...hold.map(b => b.score || 0));

  return (
    <section className="section">
      <div className="section-head">
        <h2>Today's Actions</h2>
        <div className="blurb">
          As of <strong style={{ color: "var(--ink)" }}>{today.as_of}</strong>
          {" · "}universe {today.liquid_universe_size}/{today.universe_size} liquid
          {" · "}top-{today.topk}
        </div>
      </div>
      <div className="actions-board">
        <div className="action-col" data-kind="buy">
          <div className="action-head">
            <h3>Buy</h3>
            <span className="count">{String(buy.length).padStart(2, "0")}</span>
          </div>
          {buy.length === 0 && <div className="action-empty">No new entries today.</div>}
          {buy.map((b) => (
            <div key={b.symbol} className="action-row">
              <span className="rank">#{b.rank}</span>
              <span className="sym">{b.symbol}</span>
              <span className="score-bar"><span style={{ width: `${(b.score / buyMax) * 100}%` }} /></span>
              <span className="score-num">{b.score?.toFixed(4)}</span>
            </div>
          ))}
          <div className="action-foot">
            Top-K names by model score. Cron buys these at today's close.
          </div>
        </div>

        <div className="action-col" data-kind="sell">
          <div className="action-head">
            <h3>Sell</h3>
            <span className="count">{String(sell.length).padStart(2, "0")}</span>
          </div>
          {sell.length === 0 && <div className="action-empty">No rotations today.</div>}
          {sell.map((s) => (
            <div key={s.symbol} className="action-row" style={{ display: "block", padding: "14px 20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="sym">{s.symbol}</span>
                <span style={{ marginLeft: "auto", color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  rank → #{s.rank_now}
                </span>
              </div>
              <div className="reason" style={{ paddingLeft: 0, marginTop: 6 }}>{s.reason}</div>
            </div>
          ))}
          <div className="action-foot">
            Held names that fell out of top-(K + buffer). Capital rotates; model isn't betting against them.
          </div>
        </div>

        <div className="action-col" data-kind="hold">
          <div className="action-head">
            <h3>Hold</h3>
            <span className="count">{String(hold.length).padStart(2, "0")}</span>
          </div>
          {hold.length === 0 && <div className="action-empty">Empty.</div>}
          {hold.map((h) => (
            <div key={h.symbol} className="action-row">
              <span className="rank">#{h.rank}</span>
              <span className="sym">{h.symbol}</span>
              <span className="score-bar"><span style={{ width: `${(h.score / holdMax) * 100}%` }} /></span>
              <span className="score-num">{h.score?.toFixed(4)}</span>
            </div>
          ))}
          <div className="action-foot">
            Owned and inside the buffer band. Reduces churn & trading costs.
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Open positions ────────────────────────────────────────────
function PositionsCard({ portfolio }) {
  const rows = useMemo(() =>
    [...(portfolio || [])].sort((a, b) =>
      (+b.position_value || +b.shares * +b.avg_price || 0) -
      (+a.position_value || +a.shares * +a.avg_price || 0)
    ), [portfolio]);
  const total = rows.reduce((s, r) => s + (+r.position_value || 0), 0);
  const totalPnl = rows.reduce((s, r) => s + (+r.unrealized_pnl || 0), 0);

  return (
    <div className="card flush">
      <div className="card-head">
        <span className="t-eyebrow">Open Positions · {rows.length}</span>
        <span className="meta">
          Value <strong style={{ color: "var(--ink)", fontVariantNumeric: "tabular-nums" }}>₹{fmtINR(total)}</strong>
          {" · "}P&amp;L <strong className={totalPnl >= 0 ? "pnl-pos" : "pnl-neg"}>{totalPnl >= 0 ? "+" : ""}₹{fmtINR(totalPnl)}</strong>
        </span>
      </div>
      <table className="positions">
        <thead>
          <tr>
            <th>Symbol</th>
            <th className="num">Shares</th>
            <th className="num">Avg cost</th>
            <th className="num">Last</th>
            <th className="num">Value</th>
            <th className="num">P&amp;L</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(p => {
            const shares = +p.shares || 0;
            const avg = +p.avg_price || 0;
            const last = +p.last_price || 0;
            const value = +p.position_value || shares * (last || avg);
            const pnl = +p.unrealized_pnl;
            const pnlPct = avg && last ? (last - avg) / avg : null;
            const pnlClass = pnl > 0 ? "pnl-pos" : pnl < 0 ? "pnl-neg" : "pnl-zero";
            return (
              <tr key={p.symbol}>
                <td>
                  <span className="sym-cell">
                    <span className="sym-dot" style={{ background: pnl > 0 ? "var(--buy)" : pnl < 0 ? "var(--sell)" : "var(--muted)" }} />
                    {p.symbol}
                  </span>
                </td>
                <td className="num">{fmtINR(shares)}</td>
                <td className="num">₹{fmtINR(avg, 2)}</td>
                <td className="num">{last ? `₹${fmtINR(last, 2)}` : "—"}</td>
                <td className="num">₹{fmtINR(value)}</td>
                <td className={`num ${pnlClass}`}>
                  {pnl ? (
                    <>
                      {pnl >= 0 ? "+" : ""}₹{fmtINR(Math.abs(pnl))}
                      {pnlPct != null && <span style={{ color: "var(--muted)", marginLeft: 8, fontSize: 11 }}>{fmtPct(pnlPct, 2)}</span>}
                    </>
                  ) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Decisions history & Alerts ───────────────────────────────
function DecisionsTable({ decisions }) {
  const maxBuy = Math.max(...decisions.map(d => (d.actions?.BUY || []).length), 1);
  const maxSell = Math.max(...decisions.map(d => (d.actions?.SELL || []).length), 1);
  return (
    <div className="card flush">
      <div className="card-head">
        <span className="t-eyebrow">Recent Decisions · last {decisions.length} days</span>
        <span className="meta">one row per trading day</span>
      </div>
      <table className="decisions-table">
        <thead>
          <tr>
            <th>Date</th>
            <th className="num">Universe</th>
            <th className="num">Top-K</th>
            <th className="num">Buys</th>
            <th className="num">Sells</th>
          </tr>
        </thead>
        <tbody>
          {decisions.map(d => {
            const b = (d.actions?.BUY || []).length;
            const s = (d.actions?.SELL || []).length;
            return (
              <tr key={d.as_of}>
                <td>{d.as_of}</td>
                <td className="num"><span style={{ color: "var(--muted)" }}>{d.liquid_universe_size}/</span>{d.universe_size}</td>
                <td className="num">{d.topk}</td>
                <td className="num">
                  <span className="bar-cell">
                    <span className="mini-bar"><span style={{ width: `${(b / maxBuy) * 100}%`, background: "var(--buy)" }} /></span>
                    <span style={{ color: b ? "var(--buy)" : "var(--faint)", minWidth: 18, textAlign: "right" }}>{b}</span>
                  </span>
                </td>
                <td className="num">
                  <span className="bar-cell">
                    <span className="mini-bar"><span style={{ width: `${(s / maxSell) * 100}%`, background: "var(--sell)" }} /></span>
                    <span style={{ color: s ? "var(--sell)" : "var(--faint)", minWidth: 18, textAlign: "right" }}>{s}</span>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AlertsCard({ alerts }) {
  return (
    <div className="card">
      <span className="t-eyebrow">Alerts &amp; Run Log</span>
      <div className="alerts-log">
        {alerts.map((line, i) => {
          const m = line.match(/^\[([^\]]+)\]\s*(.*)$/);
          const ts = m ? m[1] : "";
          const msg = m ? m[2] : line;
          return (
            <div key={i} className="row">
              <span className="ts">{ts}</span>
              <span>{msg}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Dashboard ─────────────────────────────────────────────────
function Dashboard({ data }) {
  return (
    <div className="page">
      <Hero equity={data.equity} />
      <ActionsBoard decisions={data.decisions} />
      <section className="section">
        <PositionsCard portfolio={data.portfolio} />
      </section>
      <section className="section">
        <div className="col-21">
          <DecisionsTable decisions={data.decisions} />
          <AlertsCard alerts={data.alerts?.lines || []} />
        </div>
      </section>
    </div>
  );
}

window.Dashboard = Dashboard;
window.Topbar = Topbar;
window.TrustStrip = TrustStrip;
