from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import json
import yfinance as yf
import pandas as pd
from bot_wrapper import bot_instance
import trading_bot_full as bot_core
import os

app = FastAPI(title="Trading Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montar archivos estáticos
# Aseguramos que los directorios existan para evitar errores al iniciar
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    with open("templates/index.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)

# --- REST Endpoints ---

@app.get("/api/prices/{symbol}")
async def get_live_price(symbol: str):
    try:
        # Format symbol for gate.io if needed (e.g., BTC_USDT)
        bot_core.SYMBOL = symbol
        price = bot_core.get_current_price(bot_instance.exchange_client)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/historical/{symbol}")
async def get_historical(symbol: str):
    # Mapeo de símbolos Gate.io a yfinance
    yf_sym = symbol.replace("_USDT", "-USD")
    try:
        data = yf.download(yf_sym, period="5d", interval="1m")
        if not data.empty:
            data.reset_index(inplace=True)
            # yf sometimes returns multiindex columns, flatten them
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [c[0] for c in data.columns]
            
            # Renombrar Datetime a time (Unix timestamp en segundos)
            if 'Datetime' in data.columns:
                data['time'] = data['Datetime'].apply(lambda x: int(pd.Timestamp(x).timestamp()))
            elif 'Date' in data.columns:
                data['time'] = data['Date'].apply(lambda x: int(pd.Timestamp(x).timestamp()))
                
            # Seleccionar solo las columnas necesarias y renombrarlas exactamente como se requiere
            res = data[['time', 'Open', 'High', 'Low', 'Close']].rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'
            }).to_dict(orient="records")
            return res
        return []
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

@app.get("/api/portfolio")
async def get_portfolio():
    return {
        "weights": bot_instance.current_portfolio,
        "sharpe_ratio": bot_instance.optimizer.sharpe_ratio_,
        "efficient_frontier": bot_instance.optimizer.efficient_frontier_
    }

@app.get("/api/signals")
async def get_signals():
    return bot_instance.latest_signals

@app.get("/api/risk")
async def get_risk():
    return bot_instance.latest_risk

@app.get("/api/metrics")
async def get_metrics():
    return bot_instance.latest_metrics

@app.get("/api/bot/status")
async def bot_status():
    return {"is_running": bot_instance.is_running}

@app.post("/api/bot/start")
async def start_bot():
    started = await bot_instance.start_bot()
    return {"success": started, "status": "running" if started else "already running"}

@app.post("/api/bot/stop")
async def stop_bot():
    stopped = await bot_instance.stop_bot()
    return {"success": stopped, "status": "stopped" if stopped else "not running"}

@app.get("/api/train")
async def manual_train():
    try:
        await bot_instance._execute_cycle()
        return {
            "success": True,
            "metrics": bot_instance.latest_metrics,
            "portfolio": bot_instance.current_portfolio,
            "risk": bot_instance.latest_risk
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

# --- WebSocket ---

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

@app.websocket("/ws/prices")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Recibir posibles mensajes del cliente
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Tarea en background para emitir precios via WS
async def broadcast_prices():
    while True:
        if manager.active_connections:
            payload = {}
            for sym in bot_instance.active_symbols:
                bot_core.SYMBOL = sym
                try:
                    price = bot_core.get_current_price(bot_instance.exchange_client)
                    payload[sym] = price
                except:
                    pass
            if payload:
                await manager.broadcast(json.dumps(payload))
        await asyncio.sleep(2) # Stream cada 2 segundos

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_prices())
