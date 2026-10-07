# Market Watcher

Personal wheel-strategy desk. Static Cloudflare Pages site.

## Files

- `index.html` — shell and tab layout
- `styles.css` — theme
- `app.js` — rendering, watchlist, charts
- `data.json` — daily snapshot, written only by the generator
- `chart.js` — local Chart.js UMD, no CDN
- `scripts/build_snapshot.py` — refresh job

The Signals tab owns the notable-setup feed. It is a scrollable card and is not mounted on the other tabs.

## Daily refresh

`scripts/build_snapshot.py` overwrites `data.json` and nothing else. Do not upload a generated `index.html`.

```bash
pip install -r requirements.txt
python scripts/build_snapshot.py
```

GitHub Actions runs the same script on weekdays after the cash close and on demand. Unusual flow is limited to 45–75 DTE, and Yahoo implied volatility is stored as a percent (the feed returns a decimal). A source that fails keeps that section from the previous snapshot.
