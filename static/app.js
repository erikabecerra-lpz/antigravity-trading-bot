document.addEventListener('DOMContentLoaded', () => {
    const activeSymbols = ['BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'BNB_USDT', 'XRP_USDT'];
    let ws;
    
    // Elements
    const timeEl = document.getElementById('current-time');
    const badgeEl = document.getElementById('bot-status-badge');
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    const btnExport = document.getElementById('btn-export');
    const priceCardsEl = document.getElementById('price-cards');
    const symbolSelector = document.getElementById('symbol-selector');
    
    // Charts
    let tvChart, candleSeries, ema20Series, ema50Series, bbUpper, bbLower, rsiSeries;
    let portfolioChartInstance, efficientFrontierInstance, roiChartInstance;

    // 1. Reloj en tiempo real
    setInterval(() => {
        const now = new Date();
        timeEl.innerText = now.toLocaleTimeString('en-US', { hour12: false });
    }, 1000);

    // 2. Estado del Bot
    async function fetchBotStatus() {
        try {
            const res = await fetch('/api/bot/status');
            const data = await res.json();
            if (data.is_running) {
                badgeEl.innerText = 'ACTIVO';
                badgeEl.className = 'badge badge-green';
            } else {
                badgeEl.innerText = 'INACTIVO';
                badgeEl.className = 'badge badge-red';
            }
        } catch (e) { console.error(e); }
    }
    fetchBotStatus();
    setInterval(fetchBotStatus, 10000);

    btnStart.addEventListener('click', async () => {
        const origText = btnStart.innerText;
        btnStart.innerText = "Iniciando y Entrenando...";
        btnStart.disabled = true;
        await fetch('/api/bot/start', { method: 'POST' });
        fetchBotStatus();
        try {
            await fetch('/api/train');
            await updateDashboardData();
        } catch(e) { console.error(e); }
        btnStart.innerText = origText;
        btnStart.disabled = false;
    });
    btnStop.addEventListener('click', async () => {
        await fetch('/api/bot/stop', { method: 'POST' });
        fetchBotStatus();
    });

    // 3. TradingView Chart Initialization
    function initCharts() {
        // Main Chart
        const chartContainer = document.getElementById('tv-chart');
        tvChart = LightweightCharts.createChart(chartContainer, {
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#8b949e' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
            timeScale: { borderColor: 'rgba(255,255,255,0.08)' }
        });
        candleSeries = tvChart.addCandlestickSeries({ upColor: '#00c896', downColor: '#ff4757', borderUpColor: '#00c896', borderDownColor: '#ff4757', wickUpColor: '#00c896', wickDownColor: '#ff4757' });
        
        // RSI Chart
        const rsiContainer = document.getElementById('rsi-chart');
        const rsiChart = LightweightCharts.createChart(rsiContainer, {
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#8b949e' },
            grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
            rightPriceScale: { borderColor: 'transparent' },
            timeScale: { visible: false }
        });
        rsiSeries = rsiChart.addLineSeries({ color: '#58a6ff', lineWidth: 2 });
        
        // Sync scrolling (basic implementation)
        tvChart.timeScale().subscribeVisibleTimeRangeChange(range => { rsiChart.timeScale().setVisibleRange(range); });
    }
    initCharts();

    // 4. Load Historical Data for Chart
    async function loadHistoricalData(symbol) {
        try {
            const res = await fetch(`/api/historical/${symbol}`);
            const data = await res.json();
            console.log('Datos recibidos:', data);
            if (data && data.length > 0) {
                candleSeries.setData(data);
                tvChart.timeScale().fitContent();
            }
        } catch (e) { console.error(e); }
    }
    loadHistoricalData(symbolSelector.value);
    symbolSelector.addEventListener('change', (e) => loadHistoricalData(e.target.value));

    // Timeframe selector functionality
    const tfButtons = document.querySelectorAll('.tf-btn');
    tfButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            tfButtons.forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            loadHistoricalData(symbolSelector.value);
        });
    });

    // 5. WebSocket Live Prices
    function connectWS() {
        const wsUrl = `ws://${window.location.host}/ws/prices`;
        ws = new WebSocket(wsUrl);
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            renderPriceCards(data);
        };
        ws.onclose = () => { setTimeout(connectWS, 2000); };
    }
    connectWS();

    function renderPriceCards(data) {
        for (const [sym, price] of Object.entries(data)) {
            let card = document.getElementById(`card-${sym}`);
            if (!card) {
                card = document.createElement('div');
                card.className = 'price-card';
                card.id = `card-${sym}`;
                card.innerHTML = `
                    <div class="price-card-header">
                        <span>${sym}</span>
                        <span class="badge badge-green">BUY</span>
                    </div>
                    <div class="price-value" id="val-${sym}">$${parseFloat(price).toFixed(2)}</div>
                `;
                priceCardsEl.appendChild(card);
            } else {
                document.getElementById(`val-${sym}`).innerText = `$${parseFloat(price).toFixed(2)}`;
            }
        }
    }

    // 6. Portfolio & Risk Metrics Dashboard
    async function updateDashboardData() {
        try {
            // Risk
            const riskRes = await fetch('/api/risk');
            const riskData = await riskRes.json();
            const tbody = document.getElementById('risk-tbody');
            tbody.innerHTML = '';
            for (const [sym, r] of Object.entries(riskData)) {
                tbody.innerHTML += `<tr>
                    <td>${sym}</td>
                    <td>$${r.entry_price.toFixed(2)}</td>
                    <td style="color: var(--accent-red)">$${r.stop_loss.toFixed(2)}</td>
                    <td style="color: var(--accent-green)">$${r.take_profit.toFixed(2)}</td>
                    <td>$${r.var_95.toFixed(2)}</td>
                </tr>`;
            }

            // Portfolio
            const portRes = await fetch('/api/portfolio');
            const portData = await portRes.json();
            if(portData.weights && Object.keys(portData.weights).length > 0) {
                document.getElementById('sharpe-val').innerText = portData.sharpe_ratio.toFixed(2);
                if (!portfolioChartInstance) {
                    const ctx = document.getElementById('portfolioChart').getContext('2d');
                    portfolioChartInstance = new Chart(ctx, {
                        type: 'doughnut',
                        data: {
                            labels: Object.keys(portData.weights),
                            datasets: [{ data: Object.values(portData.weights), backgroundColor: ['#00c896', '#58a6ff', '#e3b341', '#ff4757', '#a371f7'], borderWidth: 0 }]
                        },
                        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { color: '#f0f6fc' } } } }
                    });
                } else {
                    portfolioChartInstance.data.labels = Object.keys(portData.weights);
                    portfolioChartInstance.data.datasets[0].data = Object.values(portData.weights);
                    portfolioChartInstance.update();
                }

                if (portData.efficient_frontier && portData.efficient_frontier.length > 0) {
                    const scatterData = portData.efficient_frontier.map(p => ({x: p.volatility, y: p.return}));
                    if (!efficientFrontierInstance) {
                        const ctxEf = document.getElementById('efficientFrontierChart').getContext('2d');
                        efficientFrontierInstance = new Chart(ctxEf, {
                            type: 'scatter',
                            data: {
                                datasets: [{ label: 'Portafolios', data: scatterData, backgroundColor: 'rgba(88, 166, 255, 0.5)', pointRadius: 3 }]
                            },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display: false} }, scales: { x: { title: {display: true, text: 'Volatilidad', color: '#8b949e'} }, y: { title: {display: true, text: 'Retorno', color: '#8b949e'} } } }
                        });
                    } else {
                        efficientFrontierInstance.data.datasets[0].data = scatterData;
                        efficientFrontierInstance.update();
                    }
                }
            }

            // Metrics & Evaluation
            const metRes = await fetch('/api/metrics');
            const metData = await metRes.json();
            if(metData.hyperparameters) {
                document.getElementById('metrics-list').innerHTML = `
                    <div class="metric-item"><span class="metric-label">N_Estimators</span><span class="metric-val">${metData.hyperparameters.n_estimators || 200}</span></div>
                    <div class="metric-item"><span class="metric-label">Max Depth</span><span class="metric-val">${metData.hyperparameters.max_depth || 10}</span></div>
                    <div class="metric-item"><span class="metric-label">RMSE</span><span class="metric-val">${metData.metrics?.rmse ? metData.metrics.rmse.toFixed(4) : '-'}</span></div>
                    <div class="metric-item"><span class="metric-label">Accuracy</span><span class="metric-val">${metData.metrics?.accuracy ? (metData.metrics.accuracy * 100).toFixed(2) + '%' : '-'}</span></div>
                `;
            }
            if(metData.feature_importance) {
                let html = '';
                metData.feature_importance.slice(0,5).forEach(fi => {
                    const pct = (fi.importance * 100).toFixed(1);
                    html += `<div class="fi-row">
                        <div class="fi-label">${fi.feature}</div>
                        <div class="fi-bar-container"><div class="fi-bar" style="width: ${pct}%"></div></div>
                        <div>${pct}%</div>
                    </div>`;
                });
                document.getElementById('feature-bars').innerHTML = html;
            }
            
            if(metData.confusion_matrix) {
                const cm = metData.confusion_matrix;
                document.getElementById('confusion-matrix-grid').innerHTML = `
                    <div class="cm-cell cm-header"></div><div class="cm-cell cm-header">P. HOLD</div><div class="cm-cell cm-header">P. BUY</div><div class="cm-cell cm-header">P. SELL</div>
                    <div class="cm-cell cm-header">R. HOLD</div><div class="cm-cell cm-value">${cm[0]?.[0]||0}</div><div class="cm-cell cm-value">${cm[0]?.[1]||0}</div><div class="cm-cell cm-value">${cm[0]?.[2]||0}</div>
                    <div class="cm-cell cm-header">R. BUY</div><div class="cm-cell cm-value">${cm[1]?.[0]||0}</div><div class="cm-cell cm-value">${cm[1]?.[1]||0}</div><div class="cm-cell cm-value">${cm[1]?.[2]||0}</div>
                    <div class="cm-cell cm-header">R. SELL</div><div class="cm-cell cm-value">${cm[2]?.[0]||0}</div><div class="cm-cell cm-value">${cm[2]?.[1]||0}</div><div class="cm-cell cm-value">${cm[2]?.[2]||0}</div>
                `;
            }

            if(metData.roi_simulado && metData.roi_simulado.equity_curve) {
                const eq = metData.roi_simulado.equity_curve;
                if (!roiChartInstance) {
                    const ctxRoi = document.getElementById('roiChart').getContext('2d');
                    roiChartInstance = new Chart(ctxRoi, {
                        type: 'line',
                        data: {
                            labels: eq.map((_, i) => i),
                            datasets: [{ label: 'Capital', data: eq, borderColor: '#00c896', borderWidth: 2, fill: true, backgroundColor: 'rgba(0, 200, 150, 0.1)', pointRadius: 0 }]
                        },
                        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { display: false } } }
                    });
                } else {
                    roiChartInstance.data.labels = eq.map((_, i) => i);
                    roiChartInstance.data.datasets[0].data = eq;
                    roiChartInstance.update();
                }
            }

        } catch(e) { console.error(e); }
    }
    
    updateDashboardData();
    setInterval(updateDashboardData, 30000);
});
