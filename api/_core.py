"""Backtest runner shared by the Vercel function and the local dev server."""
import datetime, json, os, urllib.request
import _engine as E

FOMC_WEEKS = ["2026-09-14", "2026-09-15", "2026-09-17", "2026-09-18",
              "2026-10-26", "2026-10-27", "2026-10-29", "2026-10-30"]


def _get(url, key, path):
    h = {"apikey": key}
    if key.startswith("eyJ"):
        h["Authorization"] = "Bearer " + key
    return json.load(urllib.request.urlopen(urllib.request.Request(url + path, headers=h), timeout=30))


def fetch_days(d0, d1):
    """monitor_samples rows between d0 and d1 -> {date: {time: raw row dict}}"""
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"].strip()
    out, off = {}, 0
    while True:
        rows = _get(url, key, f"/rest/v1/monitor_samples?select=date_et,time_et,raw&date_et=gte.{d0}"
                              f"&date_et=lte.{d1}&order=date_et,time_et&limit=1000&offset={off}")
        for r in rows:
            if r["raw"].get("straddle_mid") in (None, ""):   # failed sample: no quotes
                continue
            out.setdefault(r["date_et"], {})[r["time_et"]] = r["raw"]
        if len(rows) < 1000:
            return out
        off += 1000


def run(p, loader=fetch_days):
    """p: {from,to,mode:auto|short,dates:[..],stop:1|2,units}"""
    if E.P is None: E.load_params()
    E.days.clear(); E.days.update(loader(p["from"], p["to"]))
    E.CONFIRM = int(p.get("stop", 1)) == 2
    scale = float(p.get("units", 10)) / 10.0
    forced = set(p.get("dates") or [])
    rows = []
    for d in sorted(E.days):
        if len(E.days[d]) < 70 or "10:01" not in E.days[d]:
            continue
        if p.get("mode") == "short":
            if d not in forced:
                continue
            dec = E.decide(d); r = E.sim_short(d, "x"); trig = (dec[0] if dec else "n/a") + " (forced short)"
        else:
            dec = E.decide(d)
            if dec is None:
                continue
            trig, side = dec[0], dec[1]
            if side is None:
                rows.append(dict(date=d, trig=trig, status="no_trade", pnl=0.0, notes="")); continue
            pf = E.post_fomc(d)
            if pf is not None and side == "L":
                if pf:
                    rows.append(dict(date=d, trig=trig, status="paper (post-FOMC surprise)", pnl=0.0, notes="")); continue
                side = "S"; trig += "->2pf"
            r = E.sim_long(d, trig) if side == "L" else E.sim_short(d, trig)
        rows.append(dict(date=d, trig=trig, status=r["status"], fill=r.get("fill"),
                         pnl=round(r["pnl"] * scale, 2), notes="; ".join(r.get("notes", []))))
    for r in rows:
        r["weekday"] = datetime.date.fromisoformat(r["date"]).strftime("%a")
    return {"params": p, "rows": rows, "total": round(sum(r["pnl"] for r in rows), 2)}


def save_run(res):
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"].strip()
    h = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        h["Authorization"] = "Bearer " + key
    def post(path, body, prefer):
        rq = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                    headers=dict(h, Prefer=prefer))
        body_out = urllib.request.urlopen(rq, timeout=30).read()
        return json.loads(body_out) if "representation" in prefer else None
    run_row = post("/rest/v1/backtest_runs", {"name": res["params"].get("name") or "web run",
                   "params": res["params"], "note": f"total {res['total']}"}, "return=representation")[0]
    post("/rest/v1/backtest_days", [dict(run_id=run_row["id"], date_et=r["date"], trigger=r["trig"], status=r["status"],
         fill=r.get("fill"), pnl=r["pnl"], notes=r["notes"]) for r in res["rows"]], "return=minimal")
    return run_row["id"]
