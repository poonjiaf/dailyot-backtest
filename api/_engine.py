"""Generic quote-replay engine. All numbers live in the private strategy parameters
(env STRATEGY_PARAMS as JSON, or a git-ignored strategy_params.json) - none are in this file."""
import datetime, json, math, os

days = {}        # filled per request: days[date][time] = row dict
CONFIRM = False  # True = a stop needs the next sample to confirm it
P = None


def load_params():
    global P
    raw = (os.environ.get("STRATEGY_PARAMS") or "").strip()
    if not raw:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "strategy_params.json")
        if not os.path.exists(path):
            raise RuntimeError("STRATEGY_PARAMS is missing or empty - add it in Vercel (Environment Variables) and redeploy")
        raw = open(path).read()
    try:
        P = json.loads(raw)
    except ValueError:
        raise RuntimeError(f"STRATEGY_PARAMS is not valid JSON (length {len(raw)}, first character {raw[:1]!r}); "
                           "it must be one line starting with {{ - re-copy it and paste it again") from None
    return P


def tk(x, mode='nearest', t=0.05):
    n = x / t
    n = math.floor(n + 1e-9) if mode == 'down' else math.ceil(n - 1e-9) if mode == 'up' else round(n)
    return round(n * t, 2)


def f(x):
    try: return float(x)
    except Exception: return None


def cand(r, p):
    try:
        return dict(po=f(r[p + '_put_outer']), pi=f(r[p + '_put_inner']), ci=f(r[p + '_call_inner']),
                    co=f(r[p + '_call_outer']), bid=f(r[p + '_bid']), mid=f(r[p + '_mid']), ask=f(r[p + '_ask']))
    except KeyError:
        return None


def val(c, S):
    pv = min(max(c['pi'] - S, 0), c['pi'] - c['po'])
    cv = min(max(S - c['ci'], 0), c['co'] - c['ci'])
    return pv + cv


def decide(day):
    C = P['cond']; rs = days[day]; r31, r10 = rs.get('09:31'), rs.get('10:01')
    if not r10: return None
    s = f(r10['straddle_mid']); s31 = f(r31['straddle_mid']) if r31 else None
    decay = None if s31 is None else s31 - s
    d = decay is not None
    c1c = s < C['s_low']
    c1 = s <= C['s_mid'] and d and decay < C['decay_cut']
    c2b = C['s_mid'] < s < C['s_high'] and d and decay > C['decay_cut']
    c2l = s <= C['s_mid'] and d and decay >= C['decay_cut']
    c3 = s >= C['s_high'] and d and decay <= C['decay_cut']
    c3a = s >= C['s_high'] and d and decay > C['decay_cut']
    if c1c:
        b0 = f(r31['bwb25_floating_mid']) if r31 else None; b1 = f(r10['bwb25_locked_mid'])
        if b0 is not None and b1 is not None and b0 - b1 > C['bwb_drop']: return ('2c', 'S', s, decay)
        return ('1c', 'L', s, decay)
    if c2b or c2l: return ('2b' if c2l else '2a', 'S', s, decay)
    if c3: return ('3', 'L', s, decay)
    if c3a: return ('3a', None, s, decay)
    if c1: return ('1', 'L', s, decay)
    return ('none', None, s, decay)


def _nxt(rs, t, col, pred):
    ts = sorted(x for x in rs if len(x) == 5); i = ts.index(t)
    if i + 1 >= len(ts): return True
    v = f(rs[ts[i + 1]][col]); return v is not None and pred(v)


def times(rs): return sorted(t for t in rs if len(t) == 5)


def _end(rs): return rs['15:59:59'] if '15:59:59' in rs else rs[max(rs)]


def sim_long(day, trig):
    L = P['long']; rs = days[day]; r10 = rs['10:01']; ts = [t for t in times(rs) if t > '10:01']
    c = {k: cand(r10, p) for k, p in P['cand_long'].items()}; c = {k: v for k, v in c.items() if v and v['mid']}
    pick = min(c, key=lambda k: c[k]['mid']); sel = c[pick]; p = P['cand_long'][pick]
    lim = min(tk(sel['mid'] - L['entry_disc'], 'down'), L['limit_cap'])
    fill = None
    for t in ts:
        if t > L['window_end']: break
        a = f(rs[t][p + '_ask'])
        if a is not None and a <= lim + 1e-9: fill = (t, lim); break
    info = dict(pick=pick, limit=lim, mid=round(sel['mid'], 2))
    if not fill: return dict(info, status='no_fill', pnl=0.0)
    tf, F0 = fill
    tp1 = tk(tk(F0, 'up', L['tp1_tick']) + L['tp1_pts'], 'nearest'); late = round(tk(F0, 'up', L['tp1_tick']) + L['late_pts'], 2)
    stop = tk(F0 - L['stop_pts'], 'down')
    settle = val(sel, f(_end(rs)['forward'])); seen = []
    tp1_hit = None; open_u = L['units_total']; pnl = 0.0; notes = []; late_done = False; peak = None

    def done(): return dict(info, status='filled', fill=F0, tf=tf, pnl=round(pnl, 2), notes=notes)
    for t in [x for x in times(rs) if x > tf]:
        r = rs[t]; mid = f(r[p + '_mid']); bid = f(r[p + '_bid'])
        if mid is None: continue
        if tp1_hit is None:
            if t >= L['late_time'] and not late_done: late_done = True; tp1 = late
            q = L['units_total'] if late_done else L['units_early']
            if bid is not None and bid >= tp1 - 1e-9:
                pnl += (tp1 - F0) * q * 100; open_u -= q; tp1_hit = (t, tp1); notes.append(f'TP1 {tp1:.2f} x{q} @{t}')
                if open_u == 0: return done()
                peak = mid; continue
            if mid <= stop + 1e-9 and (not CONFIRM or _nxt(rs, t, p + '_mid', lambda v: v <= stop + 1e-9)):
                ex = bid if bid is not None else mid; pnl += (ex - F0) * open_u * 100
                notes.append(f'flat stop {stop:.2f} @{t} out {ex:.2f}'); return done()
            if t >= L['stop2_time'] and seen and mid < min(seen):
                ex = bid if bid is not None else mid; pnl += (ex - F0) * open_u * 100
                notes.append(f'new-extreme stop @{t} out {ex:.2f}'); return done()
            seen.append(mid)
        else:
            peak = max(peak, mid)
            if bid is not None and bid >= L['tp2_target']:
                pnl += (L['tp2_target'] - F0) * open_u * 100; notes.append(f"TP2 target {L['tp2_target']} @{t}"); return done()
            if mid <= peak - L['tp2_trail']:
                ex = bid if bid is not None else mid; pnl += (ex - F0) * open_u * 100
                notes.append(f'TP2 trail out {ex:.2f} @{t}'); return done()
    pnl += (settle - F0) * open_u * 100; notes.append(f'{open_u}u settle {settle:.2f}')
    return done()


def sim_short(day, trig):
    S_ = P['short']; rs = days[day]; r10 = rs['10:01']; ts = [t for t in times(rs) if t >= '10:01']
    c = {k: cand(r10, p) for k, p in P['cand_short'].items()}; c = {k: v for k, v in c.items() if v and v['mid']}
    pick = max(c, key=lambda k: c[k]['mid']); sel = c[pick]; p = P['cand_short'][pick]
    start = tk(sel['mid'] + S_['start_off'], 'up'); floor = max(round(start - S_['floor_off'], 2), S_['floor_min'])
    if start <= S_['start_min']: start = S_['floor_min']
    fill = None
    for t in ts:
        if t > S_['window_end']: break
        b = f(rs[t][p + '_bid'])
        if b is None: continue
        if t == '10:01':
            if b >= start - 1e-9: fill = (t, start); break
            if b >= floor - 1e-9: fill = (t, tk(max(b, floor), 'up')); break
        elif b >= floor - 1e-9: fill = (t, floor); break
    info = dict(pick=pick, limit=start, mid=round(sel['mid'], 2))
    if not fill: return dict(info, status='no_fill', pnl=0.0)
    tf, F0 = fill
    tp1 = round(tk(F0, 'down', S_['tp1_tick']) - S_['tp1_pts'], 2); late = round(tk(F0, 'down', S_['tp1_tick']) - S_['late_pts'], 2)
    stop = tk(F0 + S_['stop_pts'], 'up'); settle = val(sel, f(_end(rs)['forward']))
    pnl = 0.0; units = S_['units_total']; notes = []; late_done = False; tp1_hit = None; seen = []

    def done(): return dict(info, status='filled', fill=F0, tf=tf, pnl=round(pnl, 2), notes=notes)
    for t in [x for x in times(rs) if x > tf]:
        r = rs[t]; mid = f(r[p + '_mid']); ask = f(r[p + '_ask'])
        if mid is None: continue
        if tp1_hit is None:
            if t >= S_['late_time'] and not late_done: late_done = True; tp1 = late
            q = S_['units_total'] if late_done else S_['units_early']
            if ask is not None and ask <= tp1 + 1e-9:
                pnl += (F0 - tp1) * q * 100; units -= q; tp1_hit = (t, tp1); notes.append(f'TP1 {tp1:.2f} x{q} @{t}')
                if units == 0: return done()
                continue
            if mid >= stop - 1e-9 and (not CONFIRM or _nxt(rs, t, p + '_mid', lambda v: v >= stop - 1e-9)):
                ex = ask if ask is not None else mid; pnl += (F0 - ex) * units * 100
                notes.append(f'flat stop {stop:.2f} @{t} out {ex:.2f}'); return done()
            if t >= S_['stop2_time'] and seen and mid > max(seen):
                ex = ask if ask is not None else mid; pnl += (F0 - ex) * units * 100
                notes.append(f'new-extreme stop @{t} out {ex:.2f}'); return done()
            seen.append(mid)
        else:
            if ask is not None and ask <= S_['tp2_target'] + 1e-9:
                pnl += (F0 - S_['tp2_target']) * units * 100; notes.append(f"TP2 {S_['tp2_target']:.2f} @{t}"); return done()
            if mid >= tp1_hit[1] + S_['tp2_stop_pts']:
                ex = ask if ask is not None else mid; pnl += (F0 - ex) * units * 100
                notes.append(f'TP2 stop @{t} out {ex:.2f}'); return done()
    pnl += (F0 - settle) * units * 100; notes.append(f'{units}u settle {settle:.2f}')
    return done()


def post_fomc(day):
    X = P['post_fomc']
    d = datetime.date.fromisoformat(day); p = d - datetime.timedelta(days=1)
    while p.weekday() >= 5: p -= datetime.timedelta(days=1)
    if p.isoformat() not in X['dates']: return None
    rs = days[p.isoformat()]
    crush = f(rs['13:56']['straddle_mid']) - f(rs['14:06']['straddle_mid'])
    f0 = f(rs['14:06']['forward'])
    mv = max(abs(f(rs[t]['forward']) - f0) for t in rs if t > '14:06' and rs[t]['forward'])
    return crush > X['crush'] or mv > X['move']
