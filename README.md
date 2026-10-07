# Market Watcher

Personal wheel-strategy desk. Static Cloudflare Pages site.

## Files

- `index.html` — shell and tab layout
- `styles.css` — theme
- `app.js` — rendering, watchlist, charts
- `data.json` — daily snapshot. Refresh this file only.
- `chart.js` — local Chart.js UMD, no CDN

The Signals tab owns the notable-setup feed. It is a scrollable card and is not mounted on the other tabs.

## Daily refresh

Write a new `data.json` with the same keys (`generated_at`, `tickers`, `scorecard`, `walls`, `unusual`, `setups`, …). Do not regenerate `index.html`.
