/* api-data.js — fetches real Lambda endpoints, exposes window.STATE
 * with the same field shapes the redesign components expect. Fields
 * not yet wired (rankPrev, regime, confidence, peers, hit-rates) are
 * left null so components can gracefully omit those sections.
 */

window.STATE = null; // populated after loadState()

window.PENDING = {
  rankPrev: "Yesterday-diff endpoint not yet shipped (next session).",
  regime: "Regime classifier not yet shipped (next session).",
  confidence: "Backtest hit-rate scan not yet shipped (next session).",
  peers: "Cosine-similarity peers not yet shipped (next session).",
  hitRates: "Forward-return hit-rate scoreboard not yet shipped (next session).",
};

const API_ROUTES = {
  lastRun: "/api/last_run",
  halt: "/api/halt",
  decisions: "/api/decisions",
  portfolio: "/api/portfolio",
  equity: "/api/equity",
  alerts: "/api/alerts",
  intradayMtm: "/api/intraday_mtm",
  paperTradeClock: "/api/paper_trade_clock",
  stratified: "/api/stratified",
  costSensitivity: "/api/cost_sensitivity",
  survivorship: "/api/survivorship",
  outage: "/api/outage",
  regime: "/api/regime",
  shapToday: "/api/shap_today",
  peersToday: "/api/peers_today",
  hitRates: "/api/hit_rates",
};

async function _fetchJson(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

async function _fetchAlerts() {
  // /api/alerts returns {lines: [...]} — the redesign expects {lines: [...]}.
  const r = await _fetchJson("/api/alerts");
  return r && r.lines ? r : { lines: [] };
}

async function _fetchEquity() {
  // /api/equity returns CSV-as-rows (server already converts).
  // Redesign expects array; that's exactly what we get.
  return (await _fetchJson("/api/equity")) || [];
}

async function _fetchPortfolio() {
  return (await _fetchJson("/api/portfolio")) || [];
}

async function _fetchDecisions() {
  return (await _fetchJson("/api/decisions")) || [];
}

/**
 * Bootstrap STATE from the live Lambda. Returns the populated state so
 * callers can re-render. Called once on page load by app.jsx.
 */
async function loadState() {
  const [
    lastRun, halt, decisions, portfolio, equity, alerts, intradayMtm,
    paperTradeClock, stratified, costSensitivity, survivorship, outage,
    regime, shapToday, peersToday, hitRates,
  ] = await Promise.all([
    _fetchJson(API_ROUTES.lastRun),
    _fetchJson(API_ROUTES.halt),
    _fetchDecisions(),
    _fetchPortfolio(),
    _fetchEquity(),
    _fetchAlerts(),
    _fetchJson(API_ROUTES.intradayMtm),
    _fetchJson(API_ROUTES.paperTradeClock),
    _fetchJson(API_ROUTES.stratified),
    _fetchJson(API_ROUTES.costSensitivity),
    _fetchJson(API_ROUTES.survivorship),
    _fetchJson(API_ROUTES.outage),
    _fetchJson(API_ROUTES.regime),
    _fetchJson(API_ROUTES.shapToday),
    _fetchJson(API_ROUTES.peersToday),
    _fetchJson(API_ROUTES.hitRates),
  ]);

  // Normalise shape so existing JSX components (which were written
  // against MOCK) work unmodified where possible.
  window.STATE = {
    lastRun: lastRun && !lastRun.never_run ? lastRun : null,
    halt: halt || { halted: false, reason: null },
    decisions: decisions || [],
    portfolio: portfolio || [],
    equity: equity || [],
    alerts: alerts || { lines: [] },
    intradayMtm: intradayMtm && !intradayMtm.never_run ? intradayMtm : null,
    paperTradeClock: paperTradeClock && !paperTradeClock.never_run
      ? paperTradeClock
      : null,
    stratified: stratified && stratified.scenarios ? stratified : null,
    costSensitivity:
      costSensitivity && costSensitivity.cells ? costSensitivity : null,
    survivorship: survivorship && survivorship.method ? survivorship : null,
    outage: outage && outage.scenarios ? outage : null,
    regime: regime && regime.label ? regime : null,
    shapToday: shapToday && Object.keys(shapToday).length ? shapToday : null,
    peersToday: peersToday && Object.keys(peersToday).length ? peersToday : null,
    hitRates: hitRates && Object.keys(hitRates).length ? hitRates : null,
  };
  return window.STATE;
}

async function fetchSymbolDetail(sym) {
  if (!sym) return { trades: [], rankHistory: [], timeseries: [], kiteQuote: null, kiteError: null };
  const u = encodeURIComponent(sym);
  const today = new Date();
  const sixMonthsAgo = new Date(today.getTime() - 1000 * 60 * 60 * 24 * 200);
  const fmt = (d) => d.toISOString().slice(0, 10);
  const tsUrl = `/api/analytics/timeseries?symbol=${u}&start=${fmt(sixMonthsAgo)}&end=${fmt(today)}`;

  const [trades, rankHistory, ts, kite] = await Promise.all([
    _fetchJson(`/api/trades/${u}`),
    _fetchJson(`/api/rank_history/${u}`),
    _fetchJson(tsUrl),
    _fetchJson(`/api/kite_quote?symbols=${u}`),
  ]);

  const tsRows = (ts && Array.isArray(ts.rows)) ? ts.rows : [];
  const kiteQuote = (kite && kite.symbols && kite.symbols[sym]) ? kite.symbols[sym] : null;
  const kiteError = (kite && kite.error) ? kite : null;

  return {
    trades: Array.isArray(trades) ? trades : [],
    rankHistory: Array.isArray(rankHistory) ? rankHistory : [],
    timeseries: tsRows,
    kiteQuote,
    kiteError,
    kiteAsOf: kite?.as_of || null,
  };
}

window.loadState = loadState;
window.fetchSymbolDetail = fetchSymbolDetail;
