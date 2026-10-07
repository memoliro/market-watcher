(function(){
  const root = document.documentElement;
  const saved = localStorage.getItem('market-watcher-theme') || 'dark';
  root.dataset.theme = saved;

  const PAGES = {
    wheel: ['Wheel strategy radar', 'See the market before you trade it.', 'CSP entry radar for SPY, QQQ and IWM. The setup list lives on Signals so this desk stays about the wheel.'],
    signals: ['Signal feed', 'Notable right now', 'Scorecard extremes, sentiment samples and unusual flow. Scroll inside the card.'],
    markets: ['Cross-asset', 'Global scorecard', 'Trend, momentum and RSI blended into a 0–100 score. Filter by group.'],
    macro: ['Backdrop', 'Macro snapshot', 'FRED prints plus the volatility and rate charts the wheel actually cares about.'],
    sentiment: ['Positioning', 'Sentiment', 'Put/call, COT, the weekly AAII survey and a small StockTwits sample.'],
    options: ['Derivatives', 'Options flow', 'Open-interest walls and unusual premium. This tab is no longer buried under the signal list.']
  };

  function esc(s){
    return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&','<':'<','>':'>','"':'"',"'":'&#39;'}[ch]));
  }
  function pc(v){
    if (v == null || Number.isNaN(+v)) return '—';
    return `<span class="${v>=0?'good':'bad'}">${v>=0?'+':''}${v}%</span>`;
  }
  function chartColors(){
    const light = root.dataset.theme === 'light';
    return {
      grid: light ? '#e4eaf2' : '#253040',
      tick: light ? '#5c6b7c' : '#8b98a8',
      close: light ? '#1c2836' : '#e8eef7',
      band: light ? 'rgba(39,110,241,.45)' : 'rgba(121,168,255,.55)',
      fill: light ? 'rgba(39,110,241,.08)' : 'rgba(121,168,255,.08)',
      sma: '#d08a62'
    };
  }
  function baseScales(){
    const c = chartColors();
    return {
      x:{ticks:{maxTicksLimit:8, color:c.tick}, grid:{color:c.grid}},
      y:{ticks:{color:c.tick}, grid:{color:c.grid}}
    };
  }

  function applyTheme(t){
    t = t === 'light' ? 'light' : 'dark';
    root.dataset.theme = t;
    localStorage.setItem('market-watcher-theme', t);
    document.querySelectorAll('.theme-btn').forEach(b => b.classList.toggle('active', b.dataset.themeChoice === t));
    if (window.marketWatcherRefreshChartTheme) window.marketWatcherRefreshChartTheme(t);
    if (window.marketWatcherRedraw) window.marketWatcherRedraw();
  }
  document.querySelectorAll('.theme-btn').forEach(b => b.addEventListener('click', () => applyTheme(b.dataset.themeChoice)));
  applyTheme(saved);

  const charts = {};
  let DATA = null;
  let activeTicker = null;
  let macroBuilt = false;
  let sentimentBuilt = false;
  let signalFilter = 'all';
  let groupFilter = 'All';

  function show(sec){
    document.querySelectorAll('#mainTabs button').forEach(b => b.classList.toggle('active', b.dataset.sec === sec));
    Object.keys(PAGES).forEach(id => {
      const el = document.getElementById('sec-' + id);
      if (el) el.hidden = id !== sec;
    });
    const [kicker, title, note] = PAGES[sec] || PAGES.wheel;
    document.getElementById('pageKicker').textContent = kicker;
    document.getElementById('pageTitle').textContent = title;
    document.getElementById('pageNote').textContent = note;
    if (location.hash !== '#' + sec) history.replaceState(null, '', '#' + sec);
    if (sec === 'macro' && !macroBuilt){ drawMacro(); macroBuilt = true; }
    if (sec === 'sentiment' && !sentimentBuilt){ drawSentiment(); sentimentBuilt = true; }
    if (sec === 'wheel' && activeTicker) drawTicker(activeTicker);
  }
  document.querySelectorAll('#mainTabs button').forEach(b => b.addEventListener('click', () => show(b.dataset.sec)));
  document.getElementById('openSignals').addEventListener('click', () => show('signals'));

  function classify(text){
    const s = text.toLowerCase();
    if (s.includes('unusual') || s.includes('flow') || s.includes('premium')) return 'flow';
    if (s.includes('stocktwits') || s.includes('aaii') || s.includes('bearish') || s.includes('bullish')) return 'mood';
    if (s.includes('downtrend') || s.includes('52-week low') || s.includes('low')) return 'down';
    if (s.includes('uptrend') || s.includes('52-week high') || s.includes('high')) return 'up';
    return 'mood';
  }
  function renderSignals(){
    const rows = DATA.setups || [];
    document.getElementById('signalCount').textContent = rows.length;
    document.getElementById('signalBadge').textContent = rows.length + ' SETUPS';
    const filters = [['all','All'],['up','Uptrend'],['down','Downtrend'],['flow','Flow'],['mood','Sentiment']];
    document.getElementById('signalFilters').innerHTML = filters.map(([id,label]) =>
      `<button class="chip${signalFilter===id?' active':''}" data-f="${id}">${label}</button>`).join('');
    document.querySelectorAll('#signalFilters .chip').forEach(ch => ch.onclick = () => {
      signalFilter = ch.dataset.f; renderSignals();
    });
    const shown = rows.filter(x => signalFilter === 'all' || classify(x) === signalFilter);
    const box = document.getElementById('setups');
    if (!shown.length){ box.innerHTML = '<p class="empty">Nothing in this filter.</p>'; return; }
    box.innerHTML = shown.map(x => {
      const kind = classify(x);
      const label = {up:'TREND', down:'FADE', flow:'FLOW', mood:'MOOD'}[kind];
      return `<div class="signal-row"><span class="tag ${kind}">${label}</span><span>${esc(x)}</span></div>`;
    }).join('');
  }

  function renderCards(){
    const cards = [];
    const today = (DATA.generated_at || '').slice(0, 10);
    Object.keys(DATA.tickers || {}).forEach(t => {
      const d = DATA.tickers[t];
      if (!d || d.error || !d.last) return;
      const upper = (d.bb_upper || []).filter(v => v != null).slice(-1)[0];
      const lower = d.last.lower;
      const span = upper && lower != null ? Math.max(upper - lower, 1) : 1;
      const pos = Math.max(0, Math.min(100, ((d.last.close - lower) / span) * 100));
      const sigToday = (d.entries || []).some(e => e.x === today);
      const hot = d.last.dist_to_lower_pct < 1.5;
      cards.push(`<div class="card"><div class="k">${esc(t)}</div>
        <div class="v">${d.last.close.toFixed(2)} <span class="${d.last.chg_pct>=0?'good':'bad'}">${d.last.chg_pct>=0?'+':''}${d.last.chg_pct}%</span></div>
        <div class="meter${hot?' hot':''}"><i style="width:${pos.toFixed(1)}%"></i></div>
        <div class="n">${sigToday?'<b class="good">Entry signal today</b>':(d.last.bullish?'Bullish regime':'<b class="bad">Bearish regime</b>')}
        · ${d.last.dist_to_lower_pct.toFixed(1)}% above lower band</div></div>`);
    });
    cards.push(`<div class="card"><div class="k">VIX</div><div class="v">${DATA.vix_last ?? '—'}</div>
      <div class="n">${DATA.vix_last>=20?'Elevated — richer premiums':'Calm — thin premiums'}</div></div>`);
    if (DATA.putcall && DATA.putcall.equity != null){
      cards.push(`<div class="card"><div class="k">Equity put/call</div><div class="v">${DATA.putcall.equity.toFixed(2)}</div>
        <div class="n">${esc(DATA.putcall_reading || '')}</div></div>`);
    }
    document.getElementById('cards').innerHTML = cards.join('');
  }

  function renderTape(){
    const items = [];
    Object.keys(DATA.tickers || {}).forEach(t => {
      const d = DATA.tickers[t];
      if (!d || d.error || !d.last) return;
      const c = d.last.chg_pct >= 0 ? 'good' : 'bad';
      items.push(`<div class="tick"><span class="sym">${esc(t)}</span><span class="px">${d.last.close.toFixed(2)}</span><span class="ch ${c}">${d.last.chg_pct>=0?'+':''}${d.last.chg_pct}%</span></div>`);
    });
    if (DATA.vix_last != null) items.push(`<div class="tick"><span class="sym">VIX</span><span class="px">${DATA.vix_last}</span></div>`);
    if (DATA.tnx_last != null) items.push(`<div class="tick"><span class="sym">10Y</span><span class="px">${DATA.tnx_last}%</span></div>`);
    document.getElementById('tape').innerHTML = items.join('');
  }

  const TV_SYMBOLS = {SPY:'AMEX:SPY', QQQ:'NASDAQ:QQQ', IWM:'AMEX:IWM'};
  function tvSym(s){ return TV_SYMBOLS[s] || s; }
  let wlActive = 0, WL = [];
  try { WL = JSON.parse(localStorage.getItem('mw_watchlist') || '[]'); } catch(e){ WL = []; }
  if (!WL.length) WL = ['SPY','QQQ','IWM'];
  function saveWL(){ try { localStorage.setItem('mw_watchlist', JSON.stringify(WL)); } catch(e){} }
  function loadTV(t){
    const c = document.getElementById('tvChart');
    c.innerHTML = '';
    const sc = document.createElement('script');
    sc.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    sc.async = true;
    sc.textContent = JSON.stringify({
      autosize:true, symbol:tvSym(t), interval:'D',
      theme: root.dataset.theme === 'light' ? 'light' : 'dark',
      style:'1', locale:'en', hide_side_toolbar:true,
      allow_symbol_change:true, studies:['STD;Bollinger_Bands'],
      support_host:'https://www.tradingview.com'
    });
    c.appendChild(sc);
    setTimeout(() => {
      if (!c.querySelector('iframe')) c.innerHTML = '<p class="hint">TradingView chart could not load — check the connection and refresh.</p>';
    }, 9000);
  }
  function renderWL(){
    const el = document.getElementById('watchlist');
    el.innerHTML = WL.map((x,i) => `<button class="wl-chip${i===wlActive?' active':''}" data-i="${i}">${esc(x)}<span class="wl-x" data-x="${i}" title="remove">×</span></button>`).join('')
      + '<span class="wl-add"><input id="wlInput" placeholder="+ symbol"><button id="wlAddBtn" type="button">Add</button></span>';
    el.querySelectorAll('.wl-chip').forEach(ch => {
      ch.onclick = (e) => {
        if (e.target.dataset.x !== undefined){
          WL.splice(+e.target.dataset.x, 1);
          if (wlActive >= WL.length) wlActive = 0;
          saveWL(); renderWL();
          if (WL[wlActive]) loadTV(WL[wlActive]);
          return;
        }
        wlActive = +ch.dataset.i;
        loadTV(WL[wlActive]);
        renderWL();
      };
    });
    const add = () => {
      const v = document.getElementById('wlInput').value.trim().toUpperCase().replace(/[^A-Z0-9.:^/-]/g, '');
      if (v && !WL.includes(v)){ WL.push(v); wlActive = WL.length - 1; saveWL(); loadTV(v); }
      renderWL();
    };
    document.getElementById('wlAddBtn').onclick = add;
    document.getElementById('wlInput').onkeydown = (e) => { if (e.key === 'Enter') add(); };
  }
  window.marketWatcherRefreshChartTheme = function(){
    const active = WL[wlActive];
    if (active) loadTV(active);
  };

  function drawTicker(t){
    if (!window.Chart) return;
    activeTicker = t;
    const d = DATA.tickers[t];
    const c = chartColors();
    document.getElementById('chartTitle').textContent = t + ' — price, Bollinger (20, 2), 200-day';
    const ds = [
      {label:'Lower band', data:d.bb_lower, borderColor:c.band, borderWidth:1, pointRadius:0, fill:false, tension:.1},
      {label:'Upper band', data:d.bb_upper, borderColor:c.band, borderWidth:1, pointRadius:0, fill:'-1', backgroundColor:c.fill, tension:.1},
      {label:'Close', data:d.close, borderColor:c.close, borderWidth:1.6, pointRadius:0, fill:false, tension:.1},
      {label:'200-day SMA', data:d.sma200, borderColor:c.sma, borderWidth:1.2, borderDash:[6,4], pointRadius:0, fill:false, tension:.1},
      {label:'Entry signal', data:(d.entries||[]).map(e => ({x:e.x, y:e.y})), type:'scatter', backgroundColor:'#31c48d', borderColor:'#31c48d', pointRadius:6},
      {label:'Blocked', data:(d.blocked||[]).map(e => ({x:e.x, y:e.y})), type:'scatter', backgroundColor:'#f05d6c', borderColor:'#f05d6c', pointRadius:6, pointStyle:'triangle'}
    ];
    if (charts.price) charts.price.destroy();
    charts.price = new Chart(document.getElementById('priceChart'), {
      type:'line',
      data:{labels:d.dates, datasets:ds},
      options:{
        maintainAspectRatio:false,
        interaction:{mode:'index', intersect:false},
        plugins:{legend:{labels:{boxWidth:12, color:c.tick}}},
        scales:baseScales()
      }
    });
    document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.t === t));
  }
  window.marketWatcherRedraw = function(){
    if (activeTicker && !document.getElementById('sec-wheel').hidden) drawTicker(activeTicker);
    if (macroBuilt){ macroBuilt = false; if (!document.getElementById('sec-macro').hidden){ drawMacro(); macroBuilt = true; } }
    if (sentimentBuilt){ sentimentBuilt = false; if (!document.getElementById('sec-sentiment').hidden){ drawSentiment(); sentimentBuilt = true; } }
  };

  function lineChart(id, labels, values, color){
    if (!window.Chart) return;
    if (charts[id]) charts[id].destroy();
    const c = chartColors();
    charts[id] = new Chart(document.getElementById(id), {
      type:'line',
      data:{labels, datasets:[{data:values, borderColor:color, borderWidth:1.6, pointRadius:0, tension:.15}]},
      options:{maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:baseScales()}
    });
  }
  function drawMacro(){
    lineChart('vixChart', DATA.vix.dates, DATA.vix.values, '#f2b84b');
    lineChart('tnxChart', DATA.tnx.dates, DATA.tnx.values, '#79a8ff');
  }
  function drawSentiment(){
    const hist = DATA.putcall_hist || [];
    if (window.Chart && hist.length){
      if (charts.pc) charts.pc.destroy();
      const c = chartColors();
      charts.pc = new Chart(document.getElementById('pcChart'), {
        type:'line',
        data:{labels:hist.map(x => x.d), datasets:[
          {label:'Equity', data:hist.map(x => x.equity), borderColor:'#79a8ff', pointRadius:hist.length<3?3:0},
          {label:'Index', data:hist.map(x => x.index), borderColor:'#f2b84b', pointRadius:hist.length<3?3:0},
          {label:'Total', data:hist.map(x => x.total), borderColor:c.close, pointRadius:hist.length<3?3:0}
        ]},
        options:{maintainAspectRatio:false, plugins:{legend:{labels:{color:c.tick, boxWidth:12}}}, scales:baseScales()}
      });
    }
    const names = Object.keys(DATA.cot_hist || {});
    if (window.Chart && names.length){
      if (charts.cot) charts.cot.destroy();
      const c = chartColors();
      charts.cot = new Chart(document.getElementById('cotChart'), {
        type:'bar',
        data:{labels:names, datasets:[{label:'Net', data:names.map(n => (DATA.cot[n]||{}).net || 0), backgroundColor:'#4f8cff'}]},
        options:{maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:baseScales()}
      });
    }
  }

  function renderScorecard(){
    const sc = DATA.scorecard || [];
    const groups = ['All', ...new Set(sc.map(a => a.group))];
    document.getElementById('groupFilters').innerHTML = groups.map(g =>
      `<button class="chip${groupFilter===g?' active':''}" data-g="${esc(g)}">${esc(g)}</button>`).join('');
    document.querySelectorAll('#groupFilters .chip').forEach(ch => ch.onclick = () => { groupFilter = ch.dataset.g; renderScorecard(); });
    const rows = sc.filter(a => groupFilter === 'All' || a.group === groupFilter);
    let h = '<table class="data"><tr><th>Asset</th><th>Price</th><th>1W</th><th>1M</th><th>3M</th><th>vs 200d</th><th>RSI</th><th>Trend</th></tr>';
    rows.forEach(a => {
      const col = a.score>=70?'var(--up)':a.score<=30?'var(--down)':'var(--warn)';
      h += `<tr><td><b>${esc(a.label)}</b></td><td>${Number(a.price).toLocaleString()}</td><td>${pc(a.chg_5d)}</td><td>${pc(a.chg_1m)}</td><td>${pc(a.chg_3m)}</td><td>${pc(a.vs_200d)}</td><td>${a.rsi}</td><td><div class="bar"><i style="width:${a.score}%;background:${col}"></i></div></td></tr>`;
    });
    document.getElementById('scorecard').innerHTML = h + '</table>';
  }

  function renderMacroTable(){
    const m = DATA.macro || {};
    const picks = [
      ['FEDFUNDS','Fed funds'],['CPIAUCSL','CPI'],['UNRATE','Unemployment'],['_SPREAD_10Y2Y','10Y–2Y']
    ];
    document.getElementById('macroTiles').innerHTML = picks.map(([k,label]) => {
      const d = m[k]; if (!d) return '';
      return `<div class="tile"><div class="k">${esc(label)}</div><b>${esc(d.value)}</b><div class="hint">${esc(d.change || '')} · ${esc(d.asof || '')}</div></div>`;
    }).join('');
    const order = ['CPIAUCSL','UNRATE','PAYEMS','FEDFUNDS','MORTGAGE30US','DGS10','DGS2','_SPREAD_10Y2Y','BAMLH0A0HYM2','GDP','HOUST','RSXFS'];
    let h = '<table class="data"><tr><th>Indicator</th><th>Latest</th><th>Change</th><th>As of</th></tr>';
    order.forEach(k => {
      const d = m[k]; if (!d) return;
      h += `<tr><td>${esc(d.label)}</td><td><b>${esc(d.value)}</b></td><td>${esc(d.change || '—')}</td><td class="hint">${esc(d.asof)}</td></tr>`;
    });
    document.getElementById('macroTable').innerHTML = h + '</table>';
  }

  function renderMood(){
    const a = DATA.aaii || {};
    const st = DATA.stocktwits || {};
    const bull = a.bull || 0, neu = a.neutral || 0, bear = a.bear || 0;
    const cards = [`<div class="panel"><h3>AAII spread</h3><div class="v ${(a.spread||0)>=0?'good':'bad'}" style="font-size:1.6rem;margin-top:8px">${a.spread>0?'+':''}${a.spread ?? '—'}</div>
      <div class="stack"><span style="width:${bull}%;background:var(--up)"></span><span style="width:${neu}%;background:var(--warn)"></span><span style="width:${bear}%;background:var(--down)"></span></div>
      <p class="hint">Bull ${bull}% · Neutral ${neu}% · Bear ${bear}%</p></div>`];
    Object.keys(st).forEach(sym => {
      const d = st[sym];
      cards.push(`<div class="panel"><h3>StockTwits ${esc(sym)}</h3>
        <div class="stack"><span style="width:${d.bull_pct}%;background:var(--up)"></span><span style="width:${Math.max(0,100-d.bull_pct-d.bear_pct)}%;background:var(--panel-3)"></span><span style="width:${d.bear_pct}%;background:var(--down)"></span></div>
        <p class="hint">${d.bull_pct}% bullish · ${d.bear_pct}% bearish · n=${d.total}</p></div>`);
    });
    document.getElementById('moodCards').innerHTML = cards.join('');
    document.getElementById('pcHint').textContent = DATA.putcall_reading || '';
  }

  function renderWalls(){
    const w = DATA.walls || {};
    const ks = Object.keys(w).filter(k => w[k] && w[k].expiry);
    if (!ks.length){ document.getElementById('walls').innerHTML = '<p class="empty">Unavailable this run.</p>'; return; }
    document.getElementById('walls').innerHTML = ks.map(k => {
      const d = w[k];
      const all = [...(d.supports||[]), ...(d.resistances||[])];
      const max = Math.max(...all.map(x => x.oi), 1);
      const row = (x, kind) => `<div class="lvl ${kind}"><b>${x.strike}</b><div class="track"><i style="width:${(x.oi/max*100).toFixed(1)}%"></i></div><span class="hint">${(x.oi/1000).toFixed(0)}k</span></div>`;
      return `<div class="wall"><h3>${esc(k)} · ${d.spot}</h3><p class="hint">${esc(d.expiry)} · ${d.dte}d</p>
        <div class="hint" style="margin-top:10px">Put support</div>${(d.supports||[]).map(x => row(x,'put')).join('')}
        <div class="hint" style="margin-top:10px">Call resistance</div>${(d.resistances||[]).map(x => row(x,'call')).join('')}</div>`;
    }).join('');
  }

  function renderUnusual(){
    const u = DATA.unusual || [];
    if (!u.length){ document.getElementById('unusual').innerHTML = '<p class="empty">No unusual flow in the latest scan.</p>'; return; }
    let h = '<table class="data"><tr><th>Ticker</th><th>Type</th><th>Strike</th><th>Expiry</th><th>Vol / OI</th><th>Premium</th><th>IV</th></tr>';
    u.forEach(r => {
      h += `<tr><td><b>${esc(r.ticker)}</b></td><td class="${r.type==='CALL'?'good':'bad'}">${esc(r.type)}</td><td>${r.strike}</td><td>${esc(r.expiry)}</td><td>${(r.volume/1000).toFixed(1)}k / ${(r.oi/1000).toFixed(1)}k</td><td>$${(r.premium/1e6).toFixed(1)}M</td><td>${r.iv}%</td></tr>`;
    });
    document.getElementById('unusual').innerHTML = h + '</table>';
  }

  function renderNews(){
    const n = DATA.news || [];
    document.getElementById('news').innerHTML = n.length
      ? n.map(x => `<li>${esc(x.title)}<span class="pub">${esc(x.pub || '')}</span></li>`).join('')
      : '<li>No Fed/CPI/jobs/rate headlines in the latest scan.</li>';
  }

  function boot(){
    document.getElementById('genAt').textContent = 'Updated ' + (DATA.generated_at || '');
    renderTape();
    renderCards();
    renderSignals();
    renderNews();
    renderScorecard();
    renderMacroTable();
    renderMood();
    renderWalls();
    renderUnusual();
    const tickers = Object.keys(DATA.tickers || {}).filter(t => DATA.tickers[t] && !DATA.tickers[t].error);
    document.getElementById('tabs').innerHTML = tickers.map(t => `<button data-t="${t}">${t}</button>`).join('');
    document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => drawTicker(b.dataset.t));
    renderWL();
    if (WL[0]) loadTV(WL[0]);
    if (tickers[0]) drawTicker(tickers[0]);
    const hash = (location.hash || '#wheel').slice(1);
    show(PAGES[hash] ? hash : 'wheel');
  }

  fetch('data.json').then(r => {
    if (!r.ok) throw new Error('data.json ' + r.status);
    return r.json();
  }).then(data => { DATA = data; boot(); }).catch(err => {
    console.error(err);
    document.getElementById('pageNote').textContent = 'Could not load data.json. Refresh the page.';
  });
})();
