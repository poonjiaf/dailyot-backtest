# dailyot-backtest
Private. Static page (`public/`) + Python function (`api/backtest.py`) reading Supabase `monitor_samples`.

Env vars (Vercel -> Settings -> Environment Variables, and exported locally):
- SUPABASE_URL
- SUPABASE_SERVICE_KEY   (secret key; server-side only, never NEXT_PUBLIC_)
- STRATEGY_PARAMS        (JSON of all strategy numbers; private. Locally you may use a git-ignored strategy_params.json instead.
                          Shape: strategy_params.example.json)
- APP_PASSWORD           (the page asks for it; requests without it get 401)

Local: export the 3 vars, `python3 dev.py`, open http://localhost:8000
