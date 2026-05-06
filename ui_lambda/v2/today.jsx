/* global React */
const { useMemo: _useMemo } = React;

const _PENDING = (key) => (window.PENDING && window.PENDING[key]) || "Not yet wired.";

function _PendingChip({ label, hint }) {
  return (
    <span title={hint}
          style={{ fontFamily: "var(--font-mono)", fontSize: 10, padding: "2px 8px",
                   borderRadius: 999, background: "var(--surface-2)", color: "var(--muted)",
                   border: "1px dashed var(--line)", cursor: "help" }}>
      {label} · pending
    </span>
  );
}

function _fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
  } catch { return iso; }
}

function _fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) + " IST";
  } catch { return ""; }
}

function _rankByRank(entries) {
  const map = {};
  (entries || []).forEach(e => { map[e.symbol] = e.rank; });
  return map;
}

function _bucketForRank(rank) {
  if (rank == null) return null;
  if (rank <= 5) return "top_5";
  if (rank <= 10) return "top_10";
  if (rank <= 30) return "top_30";
  if (rank <= 50) return "rank_30_50";
  if (rank <= 100) return "rank_50_100";
  if (rank <= 200) return "rank_100_200";
  return "rank_200_plus";
}

// ─── Components ──────────────────────────────────────────────

function Briefing({ decision, clock, halt, regime }) {
  const buys = decision?.actions?.BUY?.length || 0;
  const sells = decision?.actions?.SELL?.length || 0;

  const dayN = clock?.total_paper_days;
  const target = clock?.target_days;
  const dailyRet = clock?.today_metrics?.daily_return_pct;
  const lossLimit = clock?.thresholds?.daily_loss_limit_pct;

  return (
    <div className="card flush" style={{ background: "linear-gradient(135deg, var(--surface) 0%, color-mix(in srgb, var(--surface) 92%, var(--accent)) 100%)" }}>
      <div style={{ padding: "32px 36px 28px" }}>
        <div className="t-eyebrow" style={{ marginBottom: 10 }}>
          {_fmtDate(decision?.as_of)} · {_fmtTime(decision?.generated_at) || "—"}
          {halt?.halted && <span style={{ marginLeft: 12, color: "var(--sell)" }}>· HALTED: {halt.reason}</span>}
        </div>
        <h2 style={{ fontFamily: "var(--font-display)", fontSize: 36, lineHeight: 1.2, letterSpacing: "-0.02em", margin: "0 0 40px", fontWeight: 400, textWrap: "balance", paddingBottom: "0.2em" }}>
          {buys + sells} signals today.{" "}
          <span style={{ color: "var(--muted)", fontStyle: "italic" }}>
            Top-{decision?.topk || "—"} long, hold buffer {decision?.hold_buffer || "—"}.
          </span>
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24, marginTop: 24 }}>
          <Stat label="Today's signals" value={`${buys}B · ${sells}S`} sub={`universe ${decision?.liquid_universe_size || "—"}/${decision?.universe_size || "—"} liquid`} />
          {regime ? (
            <Stat label="Regime"
                  value={regime.label}
                  sub={`${regime.since_days}d · σ ${regime.vol_60d_ann_pct}% · drift ${regime.drift_60d_pct >= 0 ? "+" : ""}${regime.drift_60d_pct}%`}
                  accent />
          ) : (
            <Stat label="Regime" value="—" sub="" accent>
              <_PendingChip label="regime" hint={_PENDING("regime")} />
            </Stat>
          )}
          <Stat label="Paper-trade window"
                value={dayN != null && target ? `${dayN}/${target}` : "—"}
                sub={dailyRet != null && lossLimit != null
                  ? `today ${dailyRet >= 0 ? "+" : ""}${dailyRet.toFixed(2)}% · halt at ${lossLimit}%`
                  : ""} />
        </div>
        {regime && (
          <div style={{ marginTop: 22, padding: "12px 16px", background: "var(--surface-2)", borderRadius: 6, fontSize: 13, color: "var(--ink-2)", borderLeft: "2px solid var(--accent)" }}>
            <strong style={{ color: "var(--ink)" }}>Stance:</strong> {regime.label.toLowerCase()} regime — Sharpe <strong>{regime.sharpe_here}</strong> here vs <strong>{regime.sharpe_trend}</strong> long-run. {regime.sharpe_here < regime.sharpe_trend ? "Treat signals with proportionally less conviction." : "Conditions favourable vs long-run baseline."}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, sub, accent, children }) {
  return (
    <div>
      <div style={{ fontSize: 11, lineHeight: 1.4, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 10 }}>{label}</div>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 32, lineHeight: 1.05, color: accent ? "var(--accent)" : "var(--ink)", letterSpacing: "-0.02em" }}>
        {children || value}
      </div>
      {sub && <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6, fontFamily: "var(--font-mono)" }}>{sub}</div>}
    </div>
  );
}

function SignalCard({ kind, sym, rank, score, rankPrev, scorePrev, shap, hitRate }) {
  const isBuy = kind === "BUY";
  const rankDelta = (rank != null && rankPrev != null) ? rankPrev - rank : null;
  const scoreDelta = (score != null && scorePrev != null) ? score - scorePrev : null;
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", alignItems: "center", padding: "18px 22px", borderBottom: "1px solid var(--line)", gap: 16 }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 999, background: isBuy ? "var(--buy-soft)" : "var(--sell-soft)", color: isBuy ? "var(--buy)" : "var(--sell)" }}>{kind}</span>
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em" }}>{sym}</div>
          <div style={{ fontSize: 12, color: "var(--ink-2)", marginTop: 4 }}>
            {isBuy
              ? `Entered top-${rank || "?"} long basket.`
              : "Fell out of top-30+5 buffer — rotate."}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--muted)" }}>
            {rankPrev != null
              ? <>rank #{rankPrev} → <strong style={{ color: "var(--accent)" }}>#{rank ?? "—"}</strong></>
              : <>rank <strong style={{ color: "var(--accent)" }}>#{rank ?? "—"}</strong></>}
            {rankDelta != null && (
              <span style={{ marginLeft: 8, color: rankDelta > 0 ? "var(--buy)" : rankDelta < 0 ? "var(--sell)" : "var(--muted)" }}>
                {rankDelta > 0 ? "+" : ""}{rankDelta}
              </span>
            )}
          </div>
          {score != null && (
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
              {scorePrev != null
                ? <>score {scorePrev.toFixed(4)} → </>
                : <>score </>}
              <span style={{ color: score >= 0 ? "var(--buy)" : "var(--sell)" }}>{score >= 0 ? "+" : ""}{Number(score).toFixed(4)}</span>
              {scoreDelta != null && (
                <span style={{ marginLeft: 6, color: scoreDelta >= 0 ? "var(--buy)" : "var(--sell)" }}>
                  ({scoreDelta >= 0 ? "+" : ""}{scoreDelta.toFixed(4)})
                </span>
              )}
            </div>
          )}
        </div>
      </div>
      {shap && shap.top_contributors && shap.top_contributors.length > 0 && (
        <div style={{ padding: "12px 22px", borderBottom: "1px solid var(--line)" }}>
          <div style={{ fontSize: 10, lineHeight: 1.4, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>Top contributors</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {shap.top_contributors.slice(0, 6).map((c, i) => (
              <code key={i} style={{ fontSize: 11, fontFamily: "var(--font-mono)", padding: "3px 8px", background: "var(--surface-2)", borderRadius: 3, color: c.contribution >= 0 ? "var(--buy)" : "var(--sell)" }}>
                {c.feature} {c.contribution >= 0 ? "+" : ""}{c.contribution.toFixed(4)}
              </code>
            ))}
          </div>
        </div>
      )}
      {hitRate && hitRate["5d"] && hitRate["5d"].total > 0 && (
        <div style={{ padding: "12px 22px", borderBottom: "1px solid var(--line)" }}>
          <div style={{ fontSize: 10, lineHeight: 1.4, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>Backtest hit-rate at this rank-bucket · 2024-25</div>
          <div style={{ display: "flex", gap: 18, fontFamily: "var(--font-mono)", fontSize: 12 }}>
            {["5d", "10d", "20d"].map(h => {
              const c = hitRate[h];
              if (!c || c.total === 0) return null;
              const pct = (c.hit_rate * 100).toFixed(0);
              const vs = (c.vs_universe * 100).toFixed(2);
              return (
                <span key={h}>
                  <span style={{ color: "var(--muted)" }}>{h}</span>{" "}
                  <span style={{ color: c.hit_rate >= 0.5 ? "var(--buy)" : "var(--sell)" }}>{pct}%</span>{" "}
                  <span style={{ color: "var(--faint)" }}>({c.hits}/{c.total} · vs univ {c.vs_universe >= 0 ? "+" : ""}{vs}pp)</span>
                </span>
              );
            })}
          </div>
        </div>
      )}
      <div style={{ padding: "12px 22px", background: "var(--surface-2)", fontSize: 12, color: "var(--muted)", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {!shap && <_PendingChip label="SHAP" hint="Top-feature attribution not exported for this symbol." />}
          {!hitRate && <_PendingChip label="hit-rate" hint={_PENDING("confidence")} />}
        </span>
        <span style={{ fontFamily: "var(--font-mono)" }}>NSE: {sym}</span>
      </div>
    </div>
  );
}

function Signals({ decision, shapToday, hitRates }) {
  const buys = decision?.actions?.BUY || [];
  const sells = decision?.actions?.SELL || [];
  const all = [
    ...buys.map(b => ({ kind: "BUY", ...b })),
    ...sells.map(s => ({ kind: "SELL", ...s })),
  ];
  const shapMap = shapToday?.symbols || {};
  const hitBuckets = hitRates?.buckets || {};
  if (!all.length) {
    return (
      <div style={{ marginTop: 24, padding: 24, color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 13 }}>
        No decisions for the latest run.
      </div>
    );
  }
  return (
    <div style={{ marginTop: 24 }}>
      <div className="section-head">
        <h2>Signals</h2>
        <div className="blurb">Top-{decision?.topk || "?"} long basket vs. {decision?.hold_buffer || "?"}-name buffer. Execute these in your broker yourself.</div>
      </div>
      <div style={{ display: "grid", gap: 14 }}>
        {all.map((a, i) => {
          const r = a.rank ?? a.rank_now;
          const bucket = _bucketForRank(r);
          return (
            <SignalCard key={`${a.kind}-${a.symbol}-${i}`}
                        kind={a.kind} sym={a.symbol}
                        rank={r} score={a.score}
                        rankPrev={a.rank_prev} scorePrev={a.score_prev}
                        shap={shapMap[a.symbol]}
                        hitRate={bucket ? hitBuckets[bucket] : null} />
          );
        })}
      </div>
    </div>
  );
}

function PortfolioRanks({ portfolio, decision }) {
  if (!portfolio?.length) {
    return (
      <div className="card flush" style={{ marginTop: 24 }}>
        <div className="card-head"><span className="t-eyebrow">Open positions</span></div>
        <div style={{ padding: 24, color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 13 }}>
          Portfolio empty.
        </div>
      </div>
    );
  }
  const acts = decision?.actions || {};
  const rankMap = {};
  [...(acts.BUY || []), ...(acts.HOLD || []), ...(acts.SELL || [])].forEach(e => {
    if (!e?.symbol) return;
    const r = e.rank ?? e.rank_now;
    if (r != null) rankMap[e.symbol] = r;
  });
  const topk = decision?.topk || 30;
  const buffer = decision?.hold_buffer || 5;
  const edge = topk + buffer;

  const rows = portfolio.map(p => {
    const rank = rankMap[p.symbol];
    const bufferDist = rank != null ? edge - rank : null;
    return { sym: p.symbol, rank, bufferDist };
  });
  rows.sort((a, b) => {
    const ax = a.bufferDist == null ? Infinity : a.bufferDist;
    const bx = b.bufferDist == null ? Infinity : b.bufferDist;
    return ax - bx;
  });

  return (
    <div className="card flush" style={{ marginTop: 24 }}>
      <div className="card-head">
        <span className="t-eyebrow">Open positions · {portfolio.length} · ranked by distance from buffer</span>
        <span className="meta">closest to rotation first</span>
      </div>
      <div style={{ padding: "8px 0" }}>
        {rows.map((h, i) => {
          const unknown = h.bufferDist == null;
          const out = !unknown && h.bufferDist < 0;
          const watch = !unknown && h.bufferDist >= 0 && h.bufferDist < 5;
          const barWidth = unknown ? 0 : Math.max(0, Math.min(100, ((h.bufferDist + 6) / 36) * 100));
          return (
            <div key={h.sym} style={{ display: "grid", gridTemplateColumns: "140px 60px 1fr 160px", gap: 16, alignItems: "center", padding: "12px 24px", borderBottom: i === rows.length - 1 ? "0" : "1px solid var(--line)" }}>
              <div style={{ fontWeight: 500, fontSize: 14 }}>{h.sym}</div>
              <div style={{ fontFamily: "var(--font-mono)", color: "var(--accent)", fontSize: 13 }}>{h.rank != null ? `#${h.rank}` : "—"}</div>
              <div style={{ position: "relative", height: 6, background: "var(--surface-2)", borderRadius: 3 }}>
                <div style={{ position: "absolute", left: 0, top: 0, height: "100%", width: `${barWidth}%`, background: out ? "var(--sell)" : watch ? "var(--hold)" : "var(--buy)", borderRadius: 3, opacity: 0.7 }} />
                <div style={{ position: "absolute", left: `${(6 / 36) * 100}%`, top: -3, bottom: -3, width: 1, background: "var(--line-strong)" }} />
              </div>
              <div style={{ textAlign: "right", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                {unknown ? (
                  <span style={{ color: "var(--muted)" }}>rank n/a</span>
                ) : out ? (
                  <span style={{ color: "var(--sell)" }}>{h.bufferDist} · ROTATE</span>
                ) : watch ? (
                  <span style={{ color: "var(--hold)" }}>+{h.bufferDist} · watch</span>
                ) : (
                  <span style={{ color: "var(--muted)" }}>+{h.bufferDist} from edge</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ padding: "12px 24px", borderTop: "1px solid var(--line)", fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
        Buffer = top-{topk} to top-{edge}. A position rotates only after it falls past rank {edge}. Vertical line marks the edge.
      </div>
    </div>
  );
}

function TodayView({ state }) {
  const decisions = state?.decisions || [];
  const decision = decisions[0] || null;
  const portfolio = state?.portfolio || [];
  const clock = state?.paperTradeClock;
  const halt = state?.halt;

  if (!decision) {
    return (
      <div className="page">
        <div className="card flush" style={{ padding: 36 }}>
          <div className="t-eyebrow">No decisions yet</div>
          <p style={{ marginTop: 12, color: "var(--muted)" }}>Cron has not produced a decision JSON yet.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <Briefing decision={decision} clock={clock} halt={halt} regime={state?.regime} />
      <Signals decision={decision} shapToday={state?.shapToday} hitRates={state?.hitRates} />
      <PortfolioRanks portfolio={portfolio} decision={decision} />
    </div>
  );
}

window.TodayView = TodayView;
