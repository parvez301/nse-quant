/* global React */
const { useState: _useState, useEffect: _useEffect, useMemo: _useMemo } = React;

function _OhlcvChart({ rows, kiteQuote, kiteAsOf }) {
  if (!rows?.length) {
    return <div style={{ color: "var(--muted)", fontSize: 12, padding: "16px 0" }}>No price history.</div>;
  }
  const W = 1100, H = 360, padL = 56, padR = 16, padT = 16, padB = 28;
  const innerW = W - padL - padR;
  const priceTop = padT, priceH = 240;
  const volTop = priceTop + priceH + 8, volH = 60;

  // Synthesize today's candle from Kite OHLC + last_price so the chart
  // reflects the current trading session, not the EOD-cron parquet which
  // is a day behind. Only append if the date is strictly after the last
  // historical bar (avoids double-counting after cron catches up).
  let bars = rows.slice(-180);
  const lastHistDate = bars.length ? bars[bars.length - 1].date : null;
  const todayIso = new Date().toISOString().slice(0, 10);
  const kq = kiteQuote;
  const todayCandle = (kq && kq.ohlc && kq.last_price != null
                       && kq.ohlc.open != null && kq.ohlc.high != null
                       && kq.ohlc.low != null
                       && (lastHistDate == null || todayIso > lastHistDate))
    ? {
        date: todayIso,
        open:  +kq.ohlc.open,
        high:  Math.max(+kq.ohlc.high, +kq.last_price),
        low:   Math.min(+kq.ohlc.low, +kq.last_price),
        close: +kq.last_price,
        volume: +kq.volume || 0,
        _live: true,
      }
    : null;
  if (todayCandle) bars = [...bars, todayCandle];

  const closes = bars.map(r => +r.close);
  const highs  = bars.map(r => +r.high);
  const lows   = bars.map(r => +r.low);
  const vols   = bars.map(r => +r.volume || 0);

  let pMin = Math.min(...lows), pMax = Math.max(...highs);
  if (kiteQuote?.last_price != null) {
    pMin = Math.min(pMin, +kiteQuote.last_price);
    pMax = Math.max(pMax, +kiteQuote.last_price);
  }
  pMin *= 0.99; pMax *= 1.01;
  const vMax = Math.max(...vols, 1);

  const x = (i) => padL + (i / Math.max(1, bars.length - 1)) * innerW;
  const yPrice = (v) => priceTop + (1 - (v - pMin) / (pMax - pMin)) * priceH;
  const yVol   = (v) => volTop + (1 - v / vMax) * volH;
  const candleW = Math.max(1.5, (innerW / bars.length) * 0.65);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: H }}>
      {/* gridlines */}
      {[0, 0.25, 0.5, 0.75, 1].map((f, k) => {
        const y = priceTop + f * priceH;
        const v = pMax - f * (pMax - pMin);
        return (
          <g key={k}>
            <line x1={padL} x2={W - padR} y1={y} y2={y} stroke="var(--line)" strokeWidth="0.5" />
            <text x={padL - 6} y={y + 3} textAnchor="end" fill="var(--muted)" fontSize="10" fontFamily="var(--font-mono)">
              ₹{v.toFixed(0)}
            </text>
          </g>
        );
      })}
      {/* candles */}
      {bars.map((r, i) => {
        const xc = x(i);
        const up = +r.close >= +r.open;
        const color = up ? "var(--buy)" : "var(--sell)";
        const bodyTop = yPrice(Math.max(+r.open, +r.close));
        const bodyBot = yPrice(Math.min(+r.open, +r.close));
        const isLive = r._live;
        return (
          <g key={i}>
            <line x1={xc} x2={xc} y1={yPrice(+r.high)} y2={yPrice(+r.low)} stroke={color} strokeWidth={isLive ? 1.4 : 0.8} opacity={isLive ? 1 : 0.85} />
            <rect x={xc - candleW / 2} y={bodyTop} width={candleW} height={Math.max(1, bodyBot - bodyTop)}
                  fill={color} opacity={isLive ? 1 : 0.85}
                  stroke={isLive ? "var(--accent)" : "none"} strokeWidth={isLive ? 1.5 : 0} />
          </g>
        );
      })}
      {/* volume */}
      {bars.map((r, i) => (
        <rect key={i} x={x(i) - candleW / 2} y={yVol(+r.volume)}
              width={candleW} height={(volTop + volH) - yVol(+r.volume)}
              fill={+r.close >= +r.open ? "var(--buy)" : "var(--sell)"} opacity="0.4" />
      ))}
      {/* kite last-trade horizontal line */}
      {kiteQuote?.last_price != null && (
        <g>
          <line x1={padL} x2={W - padR} y1={yPrice(+kiteQuote.last_price)} y2={yPrice(+kiteQuote.last_price)}
                stroke="var(--accent)" strokeWidth="1.2" strokeDasharray="3 3" />
          <rect x={W - padR - 110} y={yPrice(+kiteQuote.last_price) - 9} width="106" height="18"
                fill="var(--accent)" rx="3" />
          <text x={W - padR - 6} y={yPrice(+kiteQuote.last_price) + 4} textAnchor="end"
                fontSize="11" fontFamily="var(--font-mono)" fontWeight="700" fill="var(--bg)">
            KITE ₹{(+kiteQuote.last_price).toFixed(2)}
          </text>
        </g>
      )}
      {/* date axis */}
      {bars.length > 1 && [0, Math.floor(bars.length * 0.5), bars.length - 1].map((i, k) => (
        <text key={k} x={x(i)} y={H - 6} textAnchor="middle" fill="var(--muted)" fontSize="10" fontFamily="var(--font-mono)">
          {bars[i].date}
        </text>
      ))}
    </svg>
  );
}

function _isMarketOpenIST() {
  // NSE regular session: 09:15–15:30 IST, Mon–Fri.
  const now = new Date();
  const ist = new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60 * 1000);
  const day = ist.getUTCDay(); // 0=Sun..6=Sat in the IST-shifted clock
  if (day === 0 || day === 6) return false;
  const mins = ist.getUTCHours() * 60 + ist.getUTCMinutes();
  return mins >= (9 * 60 + 15) && mins <= (15 * 60 + 30);
}

function _LiveQuoteBadge({ quote, asOf, error }) {
  if (error) {
    return (
      <div style={{ padding: "10px 14px", background: "var(--sell-soft)", color: "var(--sell)", borderRadius: 6, fontSize: 12, fontFamily: "var(--font-mono)" }}>
        Kite live quote unavailable: {error.error || "unknown"}{error.detail ? ` — ${error.detail}` : ""}
      </div>
    );
  }
  if (!quote) {
    return <div style={{ padding: "10px 14px", color: "var(--muted)", fontSize: 12, fontFamily: "var(--font-mono)" }}>No quote available (Kite may be down or symbol missing).</div>;
  }
  const last = +quote.last_price;
  const prev = +quote.prev_close;
  const change = quote.change_pct;
  const o = quote.ohlc?.open, h = quote.ohlc?.high, l = quote.ohlc?.low;
  const open = _isMarketOpenIST();
  const stamp = quote.last_trade_time || quote.timestamp || asOf || "—";
  const stateLabel = open ? "LIVE" : "CLOSED · last trade";
  const stateColor = open ? "var(--buy)" : "var(--muted)";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto auto auto auto auto auto", gap: 18, alignItems: "center", padding: "12px 16px", background: "var(--surface-2)", borderRadius: 6, fontFamily: "var(--font-mono)", fontSize: 12 }}>
      <span>
        <span style={{ color: "var(--muted)", marginRight: 6 }}>LTP</span>
        <strong style={{ color: change >= 0 ? "var(--buy)" : "var(--sell)", fontSize: 16 }}>₹{last.toFixed(2)}</strong>
        {change != null && (
          <span style={{ marginLeft: 6, color: change >= 0 ? "var(--buy)" : "var(--sell)" }}>
            {change >= 0 ? "+" : ""}{change.toFixed(2)}%
          </span>
        )}
      </span>
      {o != null && <span><span style={{ color: "var(--muted)" }}>O </span>₹{(+o).toFixed(2)}</span>}
      {h != null && <span><span style={{ color: "var(--muted)" }}>H </span>₹{(+h).toFixed(2)}</span>}
      {l != null && <span><span style={{ color: "var(--muted)" }}>L </span>₹{(+l).toFixed(2)}</span>}
      {prev != null && <span><span style={{ color: "var(--muted)" }}>prev </span>₹{(+prev).toFixed(2)}</span>}
      <span style={{ textAlign: "right", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
        <span style={{ color: stateColor, fontWeight: 600, fontSize: 11, letterSpacing: "0.05em" }}>{stateLabel}</span>
        <span style={{ color: "var(--faint)", fontSize: 11 }}>Kite · {stamp}</span>
      </span>
    </div>
  );
}

function _RankSpark({ rows }) {
  if (!rows?.length) {
    return <div style={{ color: "var(--muted)", fontSize: 12, padding: "16px 0" }}>No rank history yet.</div>;
  }
  const W = 600, H = 120, padL = 36, padR = 12, padT = 12, padB = 22;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const ranks = rows.map(r => r.rank).filter(r => r != null);
  if (!ranks.length) return <div style={{ color: "var(--muted)", fontSize: 12 }}>Rank not recorded.</div>;
  const rMin = Math.max(1, Math.min(...ranks) - 5);
  const rMax = Math.max(...ranks) + 5;
  const x = (i) => rows.length === 1 ? padL + innerW / 2 : padL + (i / (rows.length - 1)) * innerW;
  const y = (v) => padT + ((v - rMin) / (rMax - rMin)) * innerH;
  const path = rows.map((r, i) => r.rank == null ? null : `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(r.rank).toFixed(1)}`).filter(Boolean).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: H }}>
      <text x={padL - 6} y={y(rMin) + 3} textAnchor="end" fill="var(--muted)" fontSize="10" fontFamily="var(--font-mono)">#{rMin}</text>
      <text x={padL - 6} y={y(rMax) + 3} textAnchor="end" fill="var(--muted)" fontSize="10" fontFamily="var(--font-mono)">#{rMax}</text>
      <line x1={padL} x2={W - padR} y1={y(30)} y2={y(30)} stroke="var(--hold)" strokeDasharray="2 3" strokeWidth="0.5" />
      <text x={W - padR} y={y(30) - 3} textAnchor="end" fill="var(--hold)" fontSize="9" fontFamily="var(--font-mono)">top-30</text>
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
      {rows.map((r, i) => r.rank != null && (
        <circle key={i} cx={x(i)} cy={y(r.rank)} r="2.5" fill="var(--accent)" />
      ))}
      {rows.length > 1 && (
        <>
          <text x={x(0)} y={H - 6} textAnchor="start" fill="var(--muted)" fontSize="9" fontFamily="var(--font-mono)">{rows[0].date}</text>
          <text x={x(rows.length - 1)} y={H - 6} textAnchor="end" fill="var(--muted)" fontSize="9" fontFamily="var(--font-mono)">{rows[rows.length - 1].date}</text>
        </>
      )}
    </svg>
  );
}

function _TradeLedger({ trades }) {
  if (!trades?.length) {
    return <div style={{ padding: 16, color: "var(--muted)", fontSize: 12, fontFamily: "var(--font-mono)" }}>No fills logged for this symbol.</div>;
  }
  return (
    <table className="positions">
      <thead>
        <tr>
          <th>Date</th><th>Action</th>
          <th className="num">Shares</th><th className="num">Price</th>
          <th className="num">Amount</th><th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t, i) => {
          const action = (t.action || "").toUpperCase();
          const isBuy = action === "BUY";
          return (
            <tr key={i}>
              <td>{t.date}</td>
              <td>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: isBuy ? "var(--buy)" : "var(--sell)", padding: "2px 8px", background: isBuy ? "var(--buy-soft)" : "var(--sell-soft)", borderRadius: 999 }}>
                  {action}
                </span>
              </td>
              <td className="num">{t.shares}</td>
              <td className="num">₹{Number(t.price).toFixed(2)}</td>
              <td className="num">₹{Number(t.amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</td>
              <td style={{ color: "var(--muted)", fontSize: 12 }}>{t.reason || "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ExplorerProView({ state }) {
  const portfolio = state?.portfolio || [];
  const decision = state?.decisions?.[0];
  const buyPicks = decision?.actions?.BUY || [];

  const symbolUniverse = _useMemo(() => {
    const set = new Set();
    (portfolio || []).forEach(p => p.symbol && set.add(p.symbol));
    (buyPicks || []).forEach(p => p.symbol && set.add(p.symbol));
    (decision?.actions?.HOLD || []).forEach(p => p.symbol && set.add(p.symbol));
    (decision?.actions?.SELL || []).forEach(p => p.symbol && set.add(p.symbol));
    return Array.from(set).sort();
  }, [portfolio, buyPicks, decision]);

  const [picked, setPicked] = _useState(symbolUniverse[0] || "");
  const [detail, setDetail] = _useState({ trades: [], rankHistory: [], timeseries: [], kiteQuote: null, kiteError: null, kiteAsOf: null });
  const [loading, setLoading] = _useState(false);

  _useEffect(() => {
    if (!picked && symbolUniverse.length) setPicked(symbolUniverse[0]);
  }, [symbolUniverse, picked]);

  _useEffect(() => {
    if (!picked) return;
    let cancelled = false;
    setLoading(true);
    window.fetchSymbolDetail(picked).then(d => {
      if (!cancelled) { setDetail(d); setLoading(false); }
    });
    return () => { cancelled = true; };
  }, [picked]);

  const todayInfo = _useMemo(() => {
    const all = [
      ...(decision?.actions?.BUY || []).map(x => ({ ...x, kind: "BUY" })),
      ...(decision?.actions?.HOLD || []).map(x => ({ ...x, kind: "HOLD" })),
      ...(decision?.actions?.SELL || []).map(x => ({ ...x, kind: "SELL" })),
    ];
    return all.find(x => x.symbol === picked);
  }, [decision, picked]);

  return (
    <div className="page" style={{ maxWidth: 1280 }}>
      <div className="section-head">
        <h2>Explorer · Lab</h2>
        <div className="blurb">Per-symbol drilldown: rank trajectory, fills, and today's snapshot. Diagnostic chart + SHAP + peers panels still wiring up.</div>
      </div>

      <div className="card flush" style={{ marginBottom: 18 }}>
        <div className="card-head">
          <span className="t-eyebrow">Pick a symbol</span>
          <span className="meta">{symbolUniverse.length} in scope (today's basket + open positions)</span>
        </div>
        <div style={{ padding: "16px 24px", display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <select value={picked} onChange={e => setPicked(e.target.value)}
                  style={{ fontFamily: "var(--font-mono)", fontSize: 13, padding: "8px 12px", background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 6, color: "var(--ink)", minWidth: 220 }}>
            {symbolUniverse.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          {todayInfo && (
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--muted)" }}>
              today: <span style={{ color: todayInfo.kind === "BUY" ? "var(--buy)" : todayInfo.kind === "SELL" ? "var(--sell)" : "var(--ink-2)" }}>{todayInfo.kind}</span>
              {todayInfo.rank != null && <> · rank #{todayInfo.rank}</>}
              {todayInfo.rank_now != null && todayInfo.rank == null && <> · rank #{todayInfo.rank_now}</>}
              {todayInfo.score != null && <> · score {todayInfo.score >= 0 ? "+" : ""}{Number(todayInfo.score).toFixed(4)}</>}
            </span>
          )}
        </div>
      </div>

      <div className="card flush" style={{ marginBottom: 18 }}>
        <div className="card-head">
          <span className="t-eyebrow">OHLCV diagnostic · {picked || "—"}</span>
          <span className="meta">{detail.timeseries.length} daily bars · live LTP from Kite</span>
        </div>
        <div style={{ padding: "14px 24px 4px" }}>
          {loading ? <div style={{ color: "var(--muted)", fontSize: 12 }}>Loading…</div>
                   : <_LiveQuoteBadge quote={detail.kiteQuote} asOf={detail.kiteAsOf} error={detail.kiteError} />}
        </div>
        <div style={{ padding: "8px 12px 12px" }}>
          {loading ? null : <_OhlcvChart rows={detail.timeseries} kiteQuote={detail.kiteQuote} kiteAsOf={detail.kiteAsOf} />}
        </div>
        <div style={{ padding: "10px 24px 14px", borderTop: "1px solid var(--line)", fontSize: 11, color: "var(--muted)", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
          Historical candles from analytics Parquet (refreshed end-of-day cron) · today's candle synthesized from live Kite OHLC + last_price (highlighted) · dashed line = Kite last-trade · LTP ≠ official closing-auction price (set in 15:30–15:40 call auction).
        </div>
      </div>

      <div className="card flush" style={{ marginBottom: 18 }}>
        <div className="card-head">
          <span className="t-eyebrow">Rank trajectory · {picked || "—"}</span>
          <span className="meta">from decision JSONs · {detail.rankHistory.length} points</span>
        </div>
        <div style={{ padding: "12px 24px 16px" }}>
          {loading ? <div style={{ color: "var(--muted)", fontSize: 12 }}>Loading…</div>
                   : <_RankSpark rows={detail.rankHistory} />}
        </div>
      </div>

      <div className="card flush" style={{ marginBottom: 18 }}>
        <div className="card-head">
          <span className="t-eyebrow">Fills · {picked || "—"}</span>
          <span className="meta">paper trade log</span>
        </div>
        <div style={{ padding: "0 0 8px 0" }}>
          {loading ? <div style={{ padding: 16, color: "var(--muted)", fontSize: 12 }}>Loading…</div>
                   : <_TradeLedger trades={detail.trades} />}
        </div>
      </div>

      {state?.shapToday?.symbols?.[picked] && (
        <div className="card flush" style={{ marginBottom: 18 }}>
          <div className="card-head">
            <span className="t-eyebrow">SHAP · top contributors · {picked}</span>
            <span className="meta">bias {state.shapToday.symbols[picked].bias.toFixed(4)} + Σ contrib = score {state.shapToday.symbols[picked].score.toFixed(4)}</span>
          </div>
          <div style={{ padding: "12px 24px 16px" }}>
            {state.shapToday.symbols[picked].top_contributors.map((c, i) => {
              const pos = c.contribution > 0;
              const max = Math.max(...state.shapToday.symbols[picked].top_contributors.map(x => Math.abs(x.contribution)));
              return (
                <div key={i} style={{ marginBottom: 10, fontSize: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 2 }}>
                    <span><code style={{ background: "var(--surface-2)", padding: "1px 5px", borderRadius: 3, fontSize: 11, marginRight: 6 }}>{c.feature}</code><span style={{ color: "var(--muted)" }}>value {c.value.toFixed(3)}</span></span>
                    <span style={{ fontFamily: "var(--font-mono)", color: pos ? "var(--buy)" : "var(--sell)" }}>{pos ? "+" : ""}{c.contribution.toFixed(4)}</span>
                  </div>
                  <div style={{ position: "relative", height: 4, background: "var(--surface-2)", borderRadius: 2 }}>
                    <div style={{ position: "absolute", left: pos ? "50%" : `${50 - (Math.abs(c.contribution) / max) * 50}%`, width: `${(Math.abs(c.contribution) / max) * 50}%`, height: "100%", background: pos ? "var(--buy)" : "var(--sell)", borderRadius: 2 }} />
                    <div style={{ position: "absolute", left: "50%", top: -1, bottom: -1, width: 1, background: "var(--line-strong)" }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {state?.peersToday?.symbols?.[picked]?.length > 0 && (
        <div className="card flush" style={{ marginBottom: 18 }}>
          <div className="card-head">
            <span className="t-eyebrow">Statistical peers · {picked}</span>
            <span className="meta">cosine sim over today's 158 features</span>
          </div>
          <div style={{ padding: "8px 24px 16px" }}>
            {state.peersToday.symbols[picked].map(p => (
              <div key={p.symbol} onClick={() => setPicked(p.symbol)}
                   style={{ display: "grid", gridTemplateColumns: "1fr 80px 80px", gap: 12, alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--line)", fontSize: 13, cursor: "pointer" }}>
                <span style={{ fontWeight: 500 }}>{p.symbol}</span>
                <div style={{ height: 4, background: "var(--surface-2)", borderRadius: 2, position: "relative" }}>
                  <div style={{ width: `${p.similarity * 100}%`, height: "100%", background: "var(--ink-2)", borderRadius: 2 }} />
                </div>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--muted)", textAlign: "right" }}>{p.similarity.toFixed(3)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {state?.hitRates?.buckets && (
        <div className="card flush" style={{ marginBottom: 18 }}>
          <div className="card-head">
            <span className="t-eyebrow">Backtest hit-rate scoreboard</span>
            <span className="meta">{state.hitRates.n_decisions?.toLocaleString("en-IN")} decisions over walk-forward test set</span>
          </div>
          <div style={{ padding: "8px 24px 16px" }}>
            <table className="live-table">
              <thead>
                <tr>
                  <th>Bucket</th>
                  <th className="num">5d</th>
                  <th className="num">10d</th>
                  <th className="num">20d</th>
                  <th className="num">vs universe (5d)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(state.hitRates.buckets).map(([name, h]) => {
                  const c5 = h["5d"]; const c10 = h["10d"]; const c20 = h["20d"];
                  if (!c5 || c5.total === 0) return null;
                  return (
                    <tr key={name}>
                      <td>{name.replace(/_/g, " ")}</td>
                      <td className="num" style={{ color: c5.hit_rate >= 0.5 ? "var(--buy)" : "var(--sell)" }}>
                        {(c5.hit_rate * 100).toFixed(0)}% <span style={{ color: "var(--muted)", fontSize: 11 }}>({c5.hits}/{c5.total})</span>
                      </td>
                      <td className="num" style={{ color: c10?.hit_rate >= 0.5 ? "var(--buy)" : "var(--sell)" }}>
                        {c10 ? `${(c10.hit_rate * 100).toFixed(0)}%` : "—"}
                      </td>
                      <td className="num" style={{ color: c20?.hit_rate >= 0.5 ? "var(--buy)" : "var(--sell)" }}>
                        {c20 ? `${(c20.hit_rate * 100).toFixed(0)}%` : "—"}
                      </td>
                      <td className="num" style={{ color: c5.vs_universe >= 0 ? "var(--buy)" : "var(--sell)" }}>
                        {c5.vs_universe >= 0 ? "+" : ""}{(c5.vs_universe * 100).toFixed(2)}pp
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}


      <div className="card flush" style={{ marginBottom: 18 }}>
        <div className="card-head">
          <span className="t-eyebrow">Today's BUY basket</span>
          <span className="meta">{buyPicks.length} names</span>
        </div>
        <div style={{ padding: "8px 0" }}>
          {buyPicks.length === 0 && (
            <div style={{ padding: 24, color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 13 }}>No decision yet.</div>
          )}
          {buyPicks.map((p, i) => (
            <div key={p.symbol} onClick={() => setPicked(p.symbol)}
                 style={{ display: "grid", gridTemplateColumns: "60px 1fr 120px 120px", gap: 16, alignItems: "center", padding: "10px 24px", borderBottom: i === buyPicks.length - 1 ? 0 : "1px solid var(--line)", fontSize: 13, cursor: "pointer", background: p.symbol === picked ? "var(--surface-2)" : "transparent" }}>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--accent)" }}>#{p.rank}</span>
              <span style={{ fontWeight: 500 }}>{p.symbol}</span>
              <span style={{ fontFamily: "var(--font-mono)", color: p.score >= 0 ? "var(--buy)" : "var(--sell)", textAlign: "right" }}>
                {p.score >= 0 ? "+" : ""}{Number(p.score).toFixed(4)}
              </span>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--muted)", textAlign: "right", fontSize: 11 }}>NSE: {p.symbol}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card flush">
        <div className="card-head">
          <span className="t-eyebrow">Open paper positions</span>
          <span className="meta">{portfolio.length} held</span>
        </div>
        <div style={{ padding: "8px 0" }}>
          {portfolio.length === 0 && (
            <div style={{ padding: 24, color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 13 }}>No positions.</div>
          )}
          {portfolio.map((p, i) => {
            const shares = Number(p.shares);
            const avg = Number(p.avg_price);
            const last = Number(p.last_price);
            const pnl = Number(p.unrealized_pnl);
            const pnlPct = avg ? ((last - avg) / avg) * 100 : 0;
            return (
              <div key={p.symbol} onClick={() => setPicked(p.symbol)}
                   style={{ display: "grid", gridTemplateColumns: "1fr 80px 100px 100px 120px", gap: 16, alignItems: "center", padding: "10px 24px", borderBottom: i === portfolio.length - 1 ? 0 : "1px solid var(--line)", fontSize: 13, cursor: "pointer", background: p.symbol === picked ? "var(--surface-2)" : "transparent" }}>
                <span style={{ fontWeight: 500 }}>{p.symbol}</span>
                <span style={{ fontFamily: "var(--font-mono)", textAlign: "right" }}>{shares}</span>
                <span style={{ fontFamily: "var(--font-mono)", textAlign: "right", color: "var(--muted)" }}>₹{avg.toFixed(2)}</span>
                <span style={{ fontFamily: "var(--font-mono)", textAlign: "right" }}>₹{last.toFixed(2)}</span>
                <span style={{ fontFamily: "var(--font-mono)", textAlign: "right", color: pnl >= 0 ? "var(--buy)" : "var(--sell)" }}>
                  {pnl >= 0 ? "+" : ""}₹{pnl.toFixed(0)} <span style={{ color: "var(--muted)", fontSize: 11 }}>({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%)</span>
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

window.ExplorerProView = ExplorerProView;
