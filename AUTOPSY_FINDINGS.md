# TITAN — Autopsy Findings

> Code audit of the TITAN trading stack. Generated from a read-through of the
> runtime spine (data → bars → supervisor → risk → broker), the strategy layer,
> the backtest/walk-forward harness, and the research docs.
>
> **Audited commit:** `6f51113` (main, up to date with origin).
> **Scope:** ~5,800 lines. No code was changed — this is a findings list only.
> **Nothing here is a crash.** These are *drift* issues: places where the
> running code disagrees with the docs, the research, or its own intent.

Severity legend:
- 🔴 **HIGH** — could lead to trading with an unvalidated/unintended algo, or a safety/process gap.
- 🟠 **MEDIUM** — dead or silently-broken code paths; behaves differently than designed.
- 🟡 **LOW** — documentation / comment drift; misleading but harmless.

---

> ## ✅ RESOLUTION STATUS (2026-06-17) — all findings below are now FIXED
> Full details + rationale in `docs/10_changes_and_decisions.md`.
>
> | Finding | Fix |
> |---|---|
> | **H1** unvalidated strategies enableable | Auto-pilot gated (validated allowlist) **and** manual `/strategies/start` now gated too (409 unless validated or `?force=true`). |
> | **M1** 1d bars never published | `bar_writer`/`aggregator` now emit `1d` (UTC-day bucket). |
> | **M2** EXIT signals dropped | Supervisor honours strategy `EXIT` via a shared `_close_trade()` path. |
> | **M3** confidence-sizing not wired | `fixed_fractional_qty` scales by `signal.confidence` (clamped 0.1–1.0); router passes it. |
> | **M4** dead `atr_position_size` | Removed; `fixed_fractional` is the single sizer (it already does risk-on-stop sizing). |
> | **M5** duplicate backtester | `bt_runner.py` deleted; `engine.py` is authoritative. |
> | **L1** gate count drift | README now says **11** gates. |
> | **L2** "ORB-only" README | README lists ORB + the 59-variant vetting library + auto-pilot. |
> | **L3** synth timing comment | Corrected (2 ticks/sim-min, ~2s per 5m bar). |
> | **L4/L5** undeclared deps | `rapidfuzz` + `streamlit-autorefresh` added to `pyproject.toml`. |
>
> Plus (from the same batch): backtester **margin model** (leverage cap + ruin guard, no >100% DD / NaN CAGR), **promotion automation** (leaderboard SHIP → Redis validated allowlist), and **real historical backfill** verified against Angel `getCandleData`.
>
> _(Original findings retained below for the audit trail.)_

---

> **Update (decision-engine change):** the auto-pilot layer (`titan/decision/`,
> `docs/08_automation_design.md`) now enforces the validated-allowlist invariant in
> code — see **H1 (resolved for the automated path)** below.

## 🔴 HIGH

### H1 — Unvalidated strategies are live-runnable without passing the walk-forward gate
**Status: ✅ resolved for the automated path; ⚠️ still open for the manual API path.**

The new auto-pilot can **only** enable strategies in `settings.autopilot_validated_set`
(default `{orb}`), enforced in `titan/decision/selector.py:target_for` and proven by
`tests/test_decision/test_selector.py::test_killed_and_unvalidated_never_enabled_in_any_regime`.
So in decision-driven mode, `vwap_revert` / `supertrend_adx` / `tsmom` can never be armed.

**Still open:** the raw `POST /strategies/{name}/start` endpoint will still enable
`vwap_revert` / `supertrend_adx` manually (only `tsmom` is blocked via `KILLED_STRATEGIES`).
To fully close, gate `start` on the validated allowlist too, or add the two unvalidated
strategies to `KILLED_STRATEGIES` until they have a walk-forward results doc.

---

#### (original finding, retained for context)

The project's binding process (`README.md`, `scripts/run_tsmom_backtest.py`) is:
*research-rank → predeclared-threshold walk-forward → SHIP or KILL → only then wire in.*

But two strategies are registered, **not** on the kill list, and startable via the API
with **no walk-forward results file** proving they ever shipped:

- `vwap_revert` — `titan/strategies/vwap_revert.py`
- `supertrend_adx` — `titan/strategies/supertrend_adx.py`

Evidence:
- Registered: `titan/strategies/supervisor.py:45-50` (`STRATEGIES` dict has all four).
- Kill list contains only TSMOM: `titan/api/main.py:104` → `KILLED_STRATEGIES = {"tsmom"}`.
- No results doc: `docs/research/` contains only `01_tsmom*.md` and `02_news_driven.md` —
  nothing for `vwap_revert` or `supertrend_adx`.
- The research itself rates `vwap_revert` as rank #18, *"N as standalone — counter-trend
  without a regime gate is unsafe"* (`docs/02_strategy_rankings.md:30`).

**Impact:** A user running `POST /strategies/vwap_revert/start` would trade an algorithm
that (a) never cleared the ship/kill bar and (b) the project's own research recommends
against. The discipline exists on paper but isn't enforced in code for these two.

**Suggested fix:** Either run the walk-forward and commit a results doc, or add both to
`KILLED_STRATEGIES` until validated. Consider a registry that *requires* a linked
results file before a strategy can be enabled.

---

## 🟠 MEDIUM

### M1 — Daily (`1d`) strategies can never fire: bars are never published
The supervisor subscribes to `1d` bars, but the bar writer only ever produces intraday
timeframes — so the `1d` channel is silent forever.

- Supervisor subscribes to `1d`: `titan/strategies/supervisor.py:54` → `TIMEFRAMES = {"5m", "1d"}`.
- Bar writer only emits intraday: `titan/data/bar_writer.py:23` → `{"1m", "3m", "5m", "15m"}`.
- The code even admits it: `titan/strategies/supervisor.py:53` —
  *"Bar writer needs to publish bars:<symbol>:1d on daily close."* (acknowledged, never done.)

**Impact:** `TSMOM` (the only `1d` strategy) could not trade even if it weren't killed.
Any future daily strategy is silently dead on arrival.

### M2 — TSMOM is dead in three independent ways
Beyond M1, the killed TSMOM strategy is non-functional on two more axes:
1. API blocks it: `titan/api/main.py:111` (returns HTTP 409).
2. No `1d` bars ever arrive (see M1).
3. Its `EXIT` signals would be dropped anyway — the supervisor `continue`s on
   `SignalKind.EXIT` and only closes via SL/TP: `titan/strategies/supervisor.py:197-198`.

**Impact:** None today (it's killed), but #3 is a *general* trap: **any** strategy that
relies on emitting its own `EXIT` signal will have those exits silently ignored. Only
stop-loss / target exits are honored.

### M3 — TSMOM's vol-targeting is a no-op (confidence is never used for sizing)
TSMOM computes an inverse-volatility position `scale` and passes it as `Signal.confidence`
(`titan/strategies/tsmom.py:57,72`). But:
- `Signal.confidence` is documented as *"for analytics, not for sizing"* (`titan/strategies/base.py:32`).
- The router sizes purely on fixed-fractional risk and never reads `confidence`
  (confirmed: no `confidence` reference anywhere in `titan/execution/` or `titan/risk/`).

**Impact:** The core thesis of TSMOM (size down in high vol) never reaches the order.
More importantly, it signals a missing feature: **conviction-weighted sizing isn't wired**,
so any future strategy expecting confidence to affect size will be silently ignored.

### M4 — `atr_position_size` is dead code in the production path
The ATR-based sizer is defined and unit-tested but **never called** by the router or
supervisor — execution always uses `fixed_fractional_qty`.

- Defined: `titan/risk/sizing.py:33`.
- Only references are the export + tests: `titan/risk/__init__.py:2`, `tests/test_sizing.py`.
- The router hardcodes fixed-fractional: `titan/execution/router.py:43`.

**Impact:** The research explicitly recommends ATR-based sizing for ORB
(`docs/02_strategy_rankings.md:71`), but the system can't actually do it. Dead code
that looks like a feature.

### M5 — Two parallel backtest engines
There are two different backtesters with different signatures and result types:
- `titan/backtest/engine.py` — synchronous, returns `BTResult`, rich metrics
  (`load_bars`, `run_backtest(starting_equity=...)`, `to_markdown`). **This is the one
  the walk-forward script uses.**
- `titan/backtest/bt_runner.py` — asynchronous, returns `BacktestResult`, minimal.

**Impact:** Confusing for maintainers; risk of "fixing" the wrong one. `bt_runner.py`
appears to be a superseded earlier implementation.

**Suggested fix:** Delete or clearly deprecate `bt_runner.py`, or document why both exist.

---

## 🟡 LOW (documentation / comment drift)

### L1 — "8-check RiskEngine" is actually 9 checks
README and the engine's own docstring say 8 gates; the code runs 9 (the funds check is
the uncounted ninth).
- Claim: `README.md` ("8-check RiskEngine"), `titan/risk/engine.py:1-23` docstring.
- Reality: `titan/risk/engine.py:84-123` — 8 chained checks **plus** per-trade risk
  **plus** funds.

### L2 — README says ORB is "currently the only" strategy
README implies a single strategy, but the supervisor registers four (`orb`,
`vwap_revert`, `supertrend_adx`, `tsmom`).
- Claim: `README.md:33`.
- Reality: `titan/strategies/supervisor.py:45-50`.
- Ties into H1 — the two undocumented ones are also unvalidated.

### L3 — Synthetic feed timing comment has wrong math
The docstring claims *"12 ticks = 1 simulated minute"* and *"5m bars close in ~10 real
seconds"*.
- At `sim_seconds_per_tick = 30` and `tick_interval = 0.2s`
  (`titan/data/synth_feed.py:46-47`), a simulated minute is **2 ticks**, not 12, and a
  5m bar closes in roughly **2 real seconds** (10 ticks × 0.2s), not 10.
- Claim: `titan/data/synth_feed.py:15-17`.

**Impact:** Misleading when debugging "why are bars flowing this fast."

### L4 — Undeclared dependency `rapidfuzz` breaks the test suite at collection
`titan/news/entities.py` imports `rapidfuzz`, but it is **not** in `pyproject.toml`
dependencies. A clean `pip install -e ".[dev]"` then `pytest` fails at collection:
`ModuleNotFoundError: No module named 'rapidfuzz'` (in `tests/test_news/test_entities.py`).
- Reality: `grep rapidfuzz pyproject.toml` → 0 hits; `titan/news/entities.py` imports it.

**Impact:** The full suite can't run out-of-the-box; CI on a fresh env would fail.
**Fix:** ✅ added `rapidfuzz` to `[project].dependencies`.

### L5 — Undeclared dependency `streamlit-autorefresh` crashes the dashboard on load
`titan/dashboard/app.py:21` imports `streamlit_autorefresh`, not declared in
`pyproject.toml`. The dashboard renders a full-page `ModuleNotFoundError: No module
named 'streamlit_autorefresh'` instead of the UI (confirmed live via browser at
`localhost:8501`).
- Reality: `grep autorefresh pyproject.toml` → 0 hits; imported at `app.py:21,203`.

**Impact:** Dashboard is completely unusable on a fresh install — the headline UI
of the project. Same class as L4.
**Fix:** ✅ added `streamlit-autorefresh` to `[project].dependencies`.

> **Pattern:** L4 + L5 are both undeclared runtime deps. Worth a `pip check` / fresh-venv
> smoke test in CI so missing dependencies surface before runtime.

---

## Cross-cutting observation — research vs. implementation gap

The research layer (`docs/`) and the code have drifted apart:

| Research says (`docs/02_strategy_rankings.md`) | In code? |
|---|---|
| #1 pick: Pairs / stat-arb (only peer-reviewed Indian edge, Sharpe ~1.34) | ❌ not implemented |
| Recommended architecture: regime-gated hybrid (HMM + VIX + ADX overlay) | ❌ not implemented |
| #2/#3: ORB (15m index / 5m large-caps) | ✅ implemented (`orb.py`) — the only validated algo |
| #12: Supertrend+ADX ("deploy only with walk-forward") | ⚠️ implemented, **not** walk-forward-validated (H1) |
| #18: VWAP mean-reversion ("N as standalone") | ⚠️ implemented & runnable despite "no" verdict (H1) |
| TSMOM | not in the top-20 table at all; built, then killed |

**Net:** In practice, **ORB on 5m bars is the only algorithm that can actually trade**
(validated, intraday timeframe, exits via SL/TP). Everything else is either dead,
unvalidated, or unbuilt.

---

## Priority order for fixing

1. **H1** — gate or kill the two unvalidated strategies (safety/process).
2. **M2(#3) / M3** — decide whether self-emitted EXIT signals and confidence-based
   sizing should work; right now both are silently swallowed (affects all future strategies).
3. **M1** — either publish `1d` bars or drop the `1d` subscription so the intent is honest.
4. **M4 / M5** — remove dead code (`atr_position_size` wiring, duplicate backtester).
5. **L1–L3** — fix the doc/comment drift.
