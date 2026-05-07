# =============================================================================
# BOT DE TRADING ALGORÍTMICO — GATE.IO FUTURES TESTNET
# Versión: 2.0 — VM Edition con Telegram Interactivo + Plots
# Investigador: Angel Roberto Nava Solis, Ph.D.
# Modelo: VaR Paramétrico 93% | Solo pandas (sin pandas_ta)
#
# BOTONES TELEGRAM:
# ① 📊 Precio + Análisis Técnico (gráfico EMA + RSI + VaR)
# ② 💰 Rendimiento y Ganancia (P&L neto + estadísticas sesión)
# ③ 🏆 Últimas Operaciones (historial real API Gate.io + score ⭐)
# ④ 💳 Saldo de Cuenta (balance USDT real desde API Gate.io)
# =============================================================================

import gate_api
from gate_api.exceptions import GateApiException
import pandas as pd
import numpy as np
import time, sys, logging, requests, io, threading
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

# =============================================================================
# SECCIÓN 1 — CONFIGURACIÓN Y PARÁMETROS
# =============================================================================

API_KEY = "c11248f106365b95a759757378041c8d"
API_SECRET = "ac531aa7aa3676d6e6f24570f57567f616e772fd2712ea3b0ff314f65367fdd3"

TELEGRAM_BOT_TOKEN = "8506725123:AAH4i_7u8E9vMn2WNfEIaUv36uCtGqt-gC8"
TELEGRAM_CHAT_ID = "8497008173"

SYMBOL = "BTC_USDT"
SETTLE = "usdt"
TIMEFRAME = "1m"
LEVERAGE = "10"
BTC_QTY = 0.010

EMA_SHORT = 9
EMA_LONG = 21
VOLATILITY_WINDOW = 20
Z_SCORE_93 = 1.476
MAX_VAR_ALLOWED = 15.0

IS_TESTNET = True

# =============================================================================
# SECCIÓN 2 — LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# =============================================================================
# SECCIÓN 3 — ESTADO GLOBAL
# =============================================================================

trade_history = []
pos_active_type = None
pos_active_size = 0
pos_entry_price = None
pos_entry_time = None
contract_mult = None
telegram_offset = 0

# Teclado principal — 2 filas de 2 botones
MAIN_KEYBOARD = [
    [
        {"text": "📊 Precio + Gráfico", "data": "btn_precio"},
        {"text": "💰 Rendimiento", "data": "btn_rendimiento"},
    ],
    [
        {"text": "🏆 Últimas Operaciones", "data": "btn_operaciones"},
        {"text": "💳 Saldo de Cuenta", "data": "btn_saldo"},
    ]
]

# =============================================================================
# SECCIÓN 4 — FUNCIONES DE TELEGRAM
# =============================================================================

def send_telegram(message, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": target, "text": message, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Falla Telegram texto: {e}")


def send_telegram_photo(image_bytes, caption="", chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {"photo": ("chart.png", image_bytes, "image/png")}
        payload = {"chat_id": target, "caption": caption, "parse_mode": "HTML"}
        requests.post(url, data=payload, files=files, timeout=30)
    except Exception as e:
        logging.error(f"Falla Telegram foto: {e}")


def send_telegram_keyboard(message, buttons_grid, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    keyboard = {
        "inline_keyboard": [
            [{"text": b["text"], "callback_data": b["data"]} for b in row]
            for row in buttons_grid
        ]
    }
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": target,
            "text": message,
            "parse_mode": "HTML",
            "reply_markup": keyboard
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Falla Telegram keyboard: {e}")


def answer_callback(callback_query_id):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
        requests.post(url, json={"callback_query_id": callback_query_id}, timeout=5)
    except Exception:
        pass


def get_updates():
    global telegram_offset
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"offset": telegram_offset, "timeout": 10}
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("ok") and data.get("result"):
            return data["result"]
    except Exception as e:
        logging.error(f"Falla polling Telegram: {e}")
    return []


def menu(chat_id):
    """Envía el menú principal de 4 botones."""
    send_telegram_keyboard(
        "📋 <b>Menú Principal</b> — ¿Qué deseas consultar?",
        MAIN_KEYBOARD,
        chat_id=chat_id
    )

# =============================================================================
# SECCIÓN 5 — CONEXIÓN CON GATE.IO
# =============================================================================

def init_exchange():
    host = ("https://api-testnet.gateapi.io/api/v4" if IS_TESTNET
            else "https://api.gateio.ws/api/v4")
    logging.info(f"🛰️ Conectando con {'Testnet' if IS_TESTNET else 'Mainnet'}...")
    config = gate_api.Configuration(key=API_KEY, secret=API_SECRET, host=host)
    api_client = gate_api.ApiClient(config)
    futures_api = gate_api.FuturesApi(api_client)
    try:
        futures_api.list_futures_accounts(settle=SETTLE)
        futures_api.update_position_leverage(settle=SETTLE, contract=SYMBOL, leverage=LEVERAGE)
        logging.info(f"✅ Conexión OK — {SYMBOL} | {LEVERAGE}x")
        return futures_api
    except GateApiException as ex:
        logging.critical(f"❌ Auth Error: {ex.message}")
        sys.exit(1)


def get_multiplier(client):
    try:
        info = client.get_futures_contract(settle=SETTLE, contract=SYMBOL)
        mult = float(info.quanto_multiplier)
        logging.info(f"📊 Multiplicador de contrato: {mult}")
        return mult
    except GateApiException as ex:
        logging.error(f"Multiplicador no obtenido: {ex.message}")
        return None

# =============================================================================
# SECCIÓN 6 — PIPELINE DE DATOS (SOLO PANDAS, SIN PANDAS-TA)
# =============================================================================

def get_data(client, limit=200):
    """Descarga velas y calcula todos los indicadores técnicos con pandas puro."""
    try:
        candles = client.list_futures_candlesticks(
            settle=SETTLE, contract=SYMBOL, interval=TIMEFRAME, limit=limit
        )
        rows = []
        for c in candles:
            close = float(c.c)
            rows.append({
                "timestamp": int(c.t),
                "open": float(c.o) if hasattr(c, 'o') and c.o else close,
                "high": float(c.h) if hasattr(c, 'h') and c.h else close,
                "low": float(c.l) if hasattr(c, 'l') and c.l else close,
                "close": close,
                "volume": float(c.v) if hasattr(c, 'v') and c.v else 0.0,
            })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df = df.sort_values("datetime").reset_index(drop=True)

        # EMAs
        df["ema_fast"] = df["close"].ewm(span=EMA_SHORT, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=EMA_LONG, adjust=False).mean()

        # ─────────────────────────────────────────────────────────────────────
        # 🛡️ MÓDULO DE ADMINISTRACIÓN DE RIESGO — VaR PARAMÉTRICO 93%
        # ─────────────────────────────────────────────────────────────────────
        df["log_return"] = np.log(df["close"] / df["close"].shift(1))
        df["rolling_std"] = df["log_return"].rolling(window=VOLATILITY_WINDOW).std()
        df["var_93"] = df["close"] * Z_SCORE_93 * df["rolling_std"]

        # RSI 14 — cálculo manual con pandas
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_g = gain.ewm(com=13, adjust=False).mean()
        avg_l = loss.ewm(com=13, adjust=False).mean()
        rs = avg_g / avg_l.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))

        # Señales de cruce EMA
        df["signal"] = 0
        df.loc[
            (df["ema_fast"] > df["ema_slow"]) &
            (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1)), "signal"
        ] = 1
        df.loc[
            (df["ema_fast"] < df["ema_slow"]) &
            (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1)), "signal"
        ] = -1

        df = df.dropna().reset_index(drop=True)
        return df if not df.empty else None

    except Exception as e:
        logging.error(f"Error en pipeline de datos: {e}")
        return None


def get_current_price(client):
    """
    Obtiene el precio actual directamente del ticker (más robusto que get_data).
    Usado por rendimiento y saldo para no depender de indicadores.
    """
    # Método 1: ticker directo
    try:
        tickers = client.list_futures_tickers(settle=SETTLE, contract=SYMBOL)
        if tickers and tickers[0].last:
            return float(tickers[0].last)
    except Exception as e:
        logging.warning(f"Ticker fallback 1: {e}")

    # Método 2: última vela
    try:
        candles = client.list_futures_candlesticks(
            settle=SETTLE, contract=SYMBOL, interval="1m", limit=3
        )
        if candles:
            return float(candles[-1].c)
    except Exception as e:
        logging.warning(f"Ticker fallback 2: {e}")

    return None

# =============================================================================
# SECCIÓN 7 — GRÁFICO DE ANÁLISIS TÉCNICO
# =============================================================================

def generate_price_chart(df):
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 9),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
        facecolor="#0d1117"
    )

    df_plot = df.tail(80).copy()
    x = df_plot["datetime"]

    # ── Panel 1: Precio + EMAs + VaR + Señales ──────────────────────────────
    ax1.set_facecolor("#0d1117")
    ax1.plot(x, df_plot["close"], color="#c9d1d9", linewidth=1.2, alpha=0.7, label="Precio")
    ax1.fill_between(x, df_plot["close"].min() * 0.998, df_plot["close"],
                     alpha=0.04, color="#58a6ff")
    ax1.plot(x, df_plot["ema_fast"], color="#f78166", linewidth=1.6, label=f"EMA {EMA_SHORT}")
    ax1.plot(x, df_plot["ema_slow"], color="#3fb950", linewidth=1.6, label=f"EMA {EMA_LONG}")

    # Banda VaR ±
    ax1.fill_between(x,
                     df_plot["close"] - df_plot["var_93"],
                     df_plot["close"] + df_plot["var_93"],
                     alpha=0.15, color="#d29922", label="Banda VaR 93%")

    # Señales buy/sell
    buys = df_plot[df_plot["signal"] == 1]
    sells = df_plot[df_plot["signal"] == -1]
    ax1.scatter(buys["datetime"], buys["close"],
                marker="^", color="#3fb950", s=90, zorder=5, label="BUY Signal")
    ax1.scatter(sells["datetime"], sells["close"],
                marker="v", color="#f85149", s=90, zorder=5, label="SELL Signal")

    # Posición activa
    if pos_active_type and pos_entry_price:
        col = "#3fb950" if pos_active_type == "LONG" else "#f85149"
        ax1.axhline(y=pos_entry_price, color=col, linestyle="--", linewidth=1.3, alpha=0.85)
        ax1.text(x.iloc[-1], pos_entry_price,
                 f" {pos_active_type} @ ${pos_entry_price:,.2f}",
                 color=col, fontsize=8, va="center")

    # Precio actual
    last_price = df_plot["close"].iloc[-1]
    ax1.annotate(
        f"${last_price:,.2f}",
        xy=(x.iloc[-1], last_price),
        xytext=(8, 0), textcoords="offset points",
        color="#e6edf3", fontsize=9, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#161b22", edgecolor="#30363d")
    )

    last_var = df_plot["var_93"].iloc[-1]
    var_txt = "⚠️ BLOQUEADO" if last_var >= MAX_VAR_ALLOWED else "✅ OK"
    ax1.set_title(
        f"📊 {SYMBOL} | EMA {EMA_SHORT}/{EMA_LONG} | "
        f"VaR 93%: ${last_var:.2f} {var_txt} "
        f"| {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        color="#e6edf3", fontsize=10, pad=10
    )
    ax1.legend(loc="upper left", fontsize=8, facecolor="#161b22",
               edgecolor="#30363d", labelcolor="#c9d1d9")
    ax1.tick_params(colors="#8b949e", labelsize=8)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax1.spines[:].set_edgecolor("#21262d")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax1.set_xlim(x.iloc[0], x.iloc[-1])
    plt.setp(ax1.get_xticklabels(), visible=False)

    # ── Panel 2: RSI ────────────────────────────────────────────────────────
    ax2.set_facecolor("#0d1117")
    ax2.plot(x, df_plot["rsi"], color="#a5d6ff", linewidth=1.4)
    ax2.axhline(70, color="#f85149", linewidth=0.8, linestyle="--", alpha=0.7)
    ax2.axhline(30, color="#3fb950", linewidth=0.8, linestyle="--", alpha=0.7)
    ax2.fill_between(x, 70, df_plot["rsi"].clip(upper=100),
                     where=df_plot["rsi"] >= 70, alpha=0.15, color="#f85149")
    ax2.fill_between(x, df_plot["rsi"].clip(lower=0), 30,
                     where=df_plot["rsi"] <= 30, alpha=0.15, color="#3fb950")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI 14", color="#8b949e", fontsize=8)
    ax2.tick_params(colors="#8b949e", labelsize=7)
    ax2.spines[:].set_edgecolor("#21262d")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax2.set_xlim(x.iloc[0], x.iloc[-1])
    ax2.text(x.iloc[0], 72, "Sobrecompra (70)", color="#f85149", fontsize=7, alpha=0.8)
    ax2.text(x.iloc[0], 22, "Sobreventa (30)", color="#3fb950", fontsize=7, alpha=0.8)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor="#0d1117", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()

# =============================================================================
# SECCIÓN 8 — RENDIMIENTO Y P&L DE SESIÓN
# =============================================================================

def calcular_pnl_abierto(current_price):
    if pos_active_type is None or pos_entry_price is None or not contract_mult:
        return 0.0
    diff = (current_price - pos_entry_price) * (1 if pos_active_type == "LONG" else -1)
    valor = abs(pos_active_size) * contract_mult * pos_entry_price
    return round(diff / pos_entry_price * valor * int(LEVERAGE), 4)


def generate_performance_report(current_price):
    closed = [t for t in trade_history if t["status"] == "closed"]
    ganancia_neta = sum(t["pnl_usdt"] for t in closed)
    n_ops = len(closed)
    ganadoras = sum(1 for t in closed if t["pnl_usdt"] > 0)
    perdedoras = n_ops - ganadoras
    win_rate = (ganadoras / n_ops * 100) if n_ops > 0 else 0.0
    mejor = max((t["pnl_usdt"] for t in closed), default=0.0)
    peor = min((t["pnl_usdt"] for t in closed), default=0.0)
    pnl_abierto = calcular_pnl_abierto(current_price)

    e_net = "🟢" if ganancia_neta >= 0 else "🔴"
    e_open = "🟢" if pnl_abierto >= 0 else "🔴"

    txt = (
        f"📈 <b>REPORTE DE RENDIMIENTO</b>\n"
        f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        f"<b>━━ RESUMEN SESIÓN ━━</b>\n"
        f"💰 Ganancia Neta: {e_net} <b>${ganancia_neta:.4f} USDT</b>\n"
        f"📊 Total Operaciones: {n_ops}\n"
        f"✅ Ganadoras: {ganadoras}\n"
        f"❌ Perdedoras: {perdedoras}\n"
        f"🎯 Win Rate: {win_rate:.1f}%\n\n"
        f"<b>━━ ESTADÍSTICAS ━━</b>\n"
        f"🏆 Mejor Trade: +${mejor:.4f} USDT\n"
        f"💀 Peor Trade: ${peor:.4f} USDT\n\n"
    )

    if pos_active_type:
        dur = ""
        if pos_entry_time:
            mins = int((datetime.now() - pos_entry_time).total_seconds() // 60)
            dur = f" ({mins} min)"
        txt += (
            f"<b>━━ POSICIÓN ACTIVA ━━</b>\n"
            f"🔷 Tipo: <b>{pos_active_type}</b>{dur}\n"
            f"💵 Entrada: ${pos_entry_price:,.4f}\n"
            f"📍 Actual: ${current_price:,.4f}\n"
            f"💹 P&L: {e_open} <b>${pnl_abierto:.4f} USDT</b>\n\n"
        )
    else:
        txt += "<b>━━ POSICIÓN ━━</b>\n🔲 Sin posición activa\n\n"

    if closed:
        txt += "<b>━━ ÚLTIMAS 5 OPS SESIÓN ━━</b>\n"
        for t in closed[-5:][::-1]:
            e = "🟢" if t["pnl_usdt"] >= 0 else "🔴"
            txt += (
                f"{e} {t['type']} "
                f"${t['entry_price']:,.2f}→${t['exit_price']:,.2f} "
                f"P&L: <b>${t['pnl_usdt']:+.4f}</b>\n"
            )
    return txt

# =============================================================================
# SECCIÓN 9 — OPERACIONES REALES DESDE API GATE.IO + SISTEMA DE PUNTUACIÓN
# =============================================================================

def _calificar(pnl_pct):
    """Retorna (puntos, descripcion, estrellas) según el % de P&L."""
    ap = abs(pnl_pct)
    if pnl_pct > 0:
        if ap >= 2.0: return 5, "Excepcional", "⭐⭐⭐⭐⭐"
        elif ap >= 1.0: return 4, "Excelente", "⭐⭐⭐⭐"
        elif ap >= 0.5: return 3, "Buena", "⭐⭐⭐"
        elif ap >= 0.2: return 2, "Aceptable", "⭐⭐"
        else: return 1, "Marginal", "⭐"
    else:
        if ap >= 2.0: return -5, "Pérdida crítica", "💀💀💀💀💀"
        elif ap >= 1.0: return -4, "Pérdida severa", "💀💀💀💀"
        elif ap >= 0.5: return -3, "Pérdida moderada", "💀💀💀"
        elif ap >= 0.2: return -2, "Pérdida leve", "💀💀"
        else: return -1, "Pérdida mínima", "💀"


def generate_operations_report(client):
    """
    Consulta el historial real de órdenes ejecutadas en Gate.io via API.
    Solo muestra órdenes que realmente tocaron el mercado (fill_price > 0).
    Califica cada operación cerrada con sistema de puntos y estrellas.
    """
    try:
        orders = client.list_futures_orders(
            settle=SETTLE,
            contract=SYMBOL,
            status="finished",
            limit=20
        )
    except GateApiException as ex:
        return f"❌ Error API Gate.io: {ex.message}"
    except Exception as e:
        return f"❌ Error consultando órdenes: {str(e)}"

    # Filtrar solo órdenes realmente ejecutadas
    ejecutadas = [
        o for o in orders
        if o.fill_price and float(o.fill_price) > 0 and o.size != 0
    ]

    if not ejecutadas:
        return (
            f"🏆 <b>ÚLTIMAS OPERACIONES — API Gate.io</b>\n"
            f"Par: {SYMBOL} | {'🟡 TESTNET' if IS_TESTNET else '🟢 MAINNET'}\n\n"
            f"ℹ️ No hay órdenes ejecutadas registradas aún.\n"
            f"El historial se pobla conforme el bot opera."
        )

    txt = (
        f"🏆 <b>ÚLTIMAS OPERACIONES — API Gate.io</b>\n"
        f"Par: <b>{SYMBOL}</b> | {'🟡 TESTNET' if IS_TESTNET else '🟢 MAINNET'}\n"
        f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
        f"{'─'*34}\n\n"
    )

    score_total = 0
    n_calificadas = 0

    for o in ejecutadas[:10]:
        fill = float(o.fill_price)
        size = int(o.size)
        es_cierre = getattr(o, 'is_close', False)

        tipo_dir = "LONG" if size > 0 else "SHORT"
        if es_cierre:
            accion = f"🔴 CIERRE {tipo_dir}"
        else:
            accion = f"🟢 APERTURA {tipo_dir}" if size > 0 else f"🟣 APERTURA {tipo_dir}"

        ts_create = ""
        if hasattr(o, 'create_time') and o.create_time:
            ts_create = datetime.fromtimestamp(int(o.create_time)).strftime("%d/%m %H:%M")

        txt += f"<b>Orden #{str(o.id)[-6:]}</b> {accion}\n"
        txt += f"  💵 Precio ejecución: ${fill:,.4f}\n"
        txt += f"  📦 Contratos: {abs(size)}\n"
        if ts_create:
            txt += f"  🕒 {ts_create}\n"

        # P&L reportado por Gate.io (disponible en órdenes de cierre)
        pnl_raw = getattr(o, 'pnl', None)
        if pnl_raw is not None:
            try:
                pnl_usdt = float(pnl_raw)
                mult = contract_mult if contract_mult else 0.0001
                nocional = abs(size) * mult * fill
                pnl_pct = (pnl_usdt / nocional * 100) if nocional > 0 else 0.0
                puntos, desc, estrellas = _calificar(pnl_pct)
                score_total += puntos
                n_calificadas += 1
                e = "🟢" if pnl_usdt >= 0 else "🔴"
                txt += (
                    f"  {e} P&L: <b>${pnl_usdt:+.4f} USDT</b> ({pnl_pct:+.3f}%)\n"
                    f"  {estrellas} {desc} ({puntos:+d} pts)\n"
                )
            except (ValueError, TypeError):
                txt += f"  📊 P&L: disponible al cierre\n"
        else:
            txt += f"  📊 P&L: disponible al cierre\n"

        txt += "\n"

    # Score de sesión
    if n_calificadas > 0:
        if score_total >= 10: nivel = "🥇 Trader Elite"
        elif score_total >= 5: nivel = "🥈 Trader Sólido"
        elif score_total >= 1: nivel = "🥉 Trader en Desarrollo"
        elif score_total >= -4: nivel = "⚠️ Gestión de Riesgo Requerida"
        else: nivel = "🆘 Revisar Estrategia"

        txt += (
            f"{'─'*34}\n"
            f"<b>━━ SCORE TOTAL ━━</b>\n"
            f"🎯 Puntuación: <b>{score_total:+d} puntos</b>\n"
            f"🏅 Nivel: <b>{nivel}</b>\n"
        )

    return txt

# =============================================================================
# SECCIÓN 10 — SALDO DE CUENTA DESDE API GATE.IO
# =============================================================================

def get_account_balance_report(client):
    """
    Consulta el balance real de futuros USDT desde Gate.io API.
    Muestra: total, disponible, P&L no realizado, márgenes usados.
    """
    try:
        account = client.list_futures_accounts(settle=SETTLE)
        acc = account[0] if isinstance(account, list) else account

        if acc is None:
            return "❌ No se pudo obtener información de cuenta."

        total = float(getattr(acc, 'total', 0))
        available = float(getattr(acc, 'available', 0))
        unrealised_pnl = float(getattr(acc, 'unrealised_pnl', 0))
        order_margin = float(getattr(acc, 'order_margin', 0))
        pos_margin = float(getattr(acc, 'position_margin',0))
        in_dual_mode = getattr(acc, 'in_dual_mode', False)

        e_pnl = "🟢" if unrealised_pnl >= 0 else "🔴"
        e_avail = "🟢" if available > 10 else ("🟡" if available > 1 else "🔴")

        margin_used = pos_margin + order_margin
        margin_ratio = (margin_used / total * 100) if total > 0 else 0.0

        txt = (
            f"💳 <b>SALDO DE CUENTA — Gate.io</b>\n"
            f"{'🟡 TESTNET' if IS_TESTNET else '🟢 MAINNET'} | "
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"{'─'*34}\n\n"
            f"<b>━━ BALANCE USDT ━━</b>\n"
            f"💰 Total Cuenta: <b>${total:,.4f} USDT</b>\n"
            f"{e_avail} Disponible: <b>${available:,.4f} USDT</b>\n"
            f"{e_pnl} P&L No Realizado: <b>${unrealised_pnl:+.4f} USDT</b>\n\n"
            f"<b>━━ USO DE MÁRGENES ━━</b>\n"
            f"🔒 Margen Posición: ${pos_margin:,.4f} USDT\n"
            f"📋 Margen Órdenes: ${order_margin:,.4f} USDT\n"
            f"📊 Uso Total: {margin_ratio:.1f}%\n\n"
            f"<b>━━ CONFIGURACIÓN BOT ━━</b>\n"
            f"⚡ Par activo: {SYMBOL}\n"
            f"🔧 Apalancamiento: {LEVERAGE}x\n"
            f"🎯 VaR máx: ${MAX_VAR_ALLOWED} USDT\n"
            f"🔑 Modo dual: {'Sí' if in_dual_mode else 'No'}\n"
        )

        # Alertas de margen
        if margin_ratio > 80:
            txt += f"\n⚠️ <b>ALERTA: Uso de margen crítico ({margin_ratio:.1f}%)</b>"
        elif margin_ratio > 50:
            txt += f"\n🟡 Advertencia: Uso de margen moderado ({margin_ratio:.1f}%)"

        return txt

    except GateApiException as ex:
        logging.error(f"Error balance API: {ex.message}")
        return f"❌ Error API Gate.io: {ex.message}"
    except Exception as e:
        logging.error(f"Error balance: {e}")
        return f"❌ Error inesperado: {str(e)}"

# =============================================================================
# SECCIÓN 11 — EJECUCIÓN DE ÓRDENES
# =============================================================================

def place_order(client, size):
    try:
        order = gate_api.FuturesOrder(contract=SYMBOL, size=int(size), price='0', tif='ioc')
        resp = client.create_futures_order(SETTLE, futures_order=order)
        time.sleep(1.5)
        status = client.get_futures_order(SETTLE, resp.id)
        if status.status == 'finished' and status.fill_price:
            fill = float(status.fill_price)
            logging.info(f"🚀 Orden ejecutada @ ${fill:,.4f}")
            return fill
        return None
    except GateApiException as ex:
        logging.error(f"Error en orden: {ex.message}")
        return None

# =============================================================================
# SECCIÓN 12 — HANDLERS INDIVIDUALES DE CADA BOTÓN
# =============================================================================

def _cmd_precio(client, chat_id):
    send_telegram("⏳ Generando análisis técnico...", chat_id=chat_id)
    df = get_data(client, limit=200)
    if df is None or df.empty:
        send_telegram("❌ No se pudieron obtener datos del mercado.", chat_id=chat_id)
        menu(chat_id)
        return

    img_bytes = generate_price_chart(df)
    last = df.iloc[-1]

    trend = "📈 Alcista" if last["ema_fast"] > last["ema_slow"] else "📉 Bajista"
    rsi_label = (
        "🔴 Sobrecompra" if last["rsi"] > 70 else
        "🟢 Sobreventa" if last["rsi"] < 30 else "⚪ Neutral"
    )
    var_label = "⚠️ BLOQUEADO" if last["var_93"] >= MAX_VAR_ALLOWED else "✅ Aceptable"

    caption = (
        f"📊 <b>{SYMBOL}</b> | {datetime.now().strftime('%H:%M:%S')}\n"
        f"💵 Precio: <b>${last['close']:,.2f}</b>\n"
        f"📉 VaR 93%: ${last['var_93']:.4f} {var_label}\n"
        f"📈 EMA {EMA_SHORT}: ${last['ema_fast']:,.2f} | EMA {EMA_LONG}: ${last['ema_slow']:,.2f}\n"
        f"📊 RSI 14: {last['rsi']:.1f} {rsi_label}\n"
        f"🧭 Tendencia: {trend}\n"
    )
    if trade_history:
        ul = trade_history[-1]
        estado = "🔷 ABIERTO" if ul["status"] == "open" else "⬛ CERRADO"
        caption += (
            f"\n<b>Último movimiento sesión:</b>\n"
            f"{estado} {ul['type']} @ ${ul['entry_price']:,.4f}"
        )

    send_telegram_photo(img_bytes, caption=caption, chat_id=chat_id)
    menu(chat_id)


def _cmd_rendimiento(client, chat_id):
    send_telegram("⏳ Calculando rendimiento...", chat_id=chat_id)
    # FIX: usa ticker directo — no get_data que requiere 20+ velas para dropna
    current_price = get_current_price(client)
    if current_price is None:
        send_telegram(
            "❌ No se pudo obtener el precio actual.\n"
            "Verifica que el bot esté conectado a Gate.io.",
            chat_id=chat_id
        )
        menu(chat_id)
        return
    reporte = generate_performance_report(current_price)
    send_telegram(reporte, chat_id=chat_id)
    menu(chat_id)


def _cmd_operaciones(client, chat_id):
    send_telegram("⏳ Consultando historial en Gate.io API...", chat_id=chat_id)
    reporte = generate_operations_report(client)
    send_telegram(reporte, chat_id=chat_id)
    menu(chat_id)


def _cmd_saldo(client, chat_id):
    send_telegram("⏳ Consultando saldo en Gate.io...", chat_id=chat_id)
    reporte = get_account_balance_report(client)
    send_telegram(reporte, chat_id=chat_id)
    menu(chat_id)

# =============================================================================
# SECCIÓN 13 — LISTENER DE COMANDOS TELEGRAM (HILO PARALELO)
# =============================================================================

def handle_commands(exchange_client):
    global telegram_offset
    logging.info("🤖 Listener de comandos Telegram activo.")

    BTN_MAP = {
        "btn_precio": _cmd_precio,
        "btn_rendimiento": _cmd_rendimiento,
        "btn_operaciones": _cmd_operaciones,
        "btn_saldo": _cmd_saldo,
    }
    CMD_MAP = {
        "/precio": _cmd_precio,
        "/rendimiento": _cmd_rendimiento,
        "/operaciones": _cmd_operaciones,
        "/saldo": _cmd_saldo,
    }

    while True:
        try:
            updates = get_updates()
            for update in updates:
                telegram_offset = update["update_id"] + 1

                # ── Mensajes de texto ────────────────────────────────────────
                if "message" in update:
                    msg = update["message"]
                    chat_id = str(msg["chat"]["id"])
                    raw = msg.get("text", "").strip()
                    cmd = raw.lower() if raw.startswith("/") else f"/{raw.lower()}"

                    if cmd == "/start":
                        send_telegram_keyboard(
                            f"🤖 <b>Crypto Navix AI Bot v2.0</b>\n"
                            f"Par: {SYMBOL} | VaR 93% | EMA {EMA_SHORT}/{EMA_LONG}\n"
                            f"{'🟡 Testnet' if IS_TESTNET else '🟢 Mainnet'}\n\n"
                            "Selecciona una opción:",
                            MAIN_KEYBOARD,
                            chat_id=chat_id
                        )
                    elif cmd in CMD_MAP:
                        CMD_MAP[cmd](exchange_client, chat_id)
                    else:
                        menu(chat_id)

                # ── Callbacks de botones ─────────────────────────────────────
                elif "callback_query" in update:
                    cb = update["callback_query"]
                    chat_id = str(cb["message"]["chat"]["id"])
                    data = cb.get("data", "")
                    answer_callback(cb["id"])

                    if data in BTN_MAP:
                        BTN_MAP[data](exchange_client, chat_id)
                    else:
                        menu(chat_id)

        except Exception as e:
            logging.error(f"Error en handle_commands: {e}")

        time.sleep(1)

# =============================================================================
# SECCIÓN 14 — LOOP PRINCIPAL DE TRADING
# =============================================================================

def main():
    global pos_active_type, pos_active_size, pos_entry_price, pos_entry_time
    global contract_mult

    exchange_client = init_exchange()
    contract_mult = get_multiplier(exchange_client)

    if not contract_mult:
        sys.exit(1)

    # Hilo paralelo de escucha de Telegram
    cmd_thread = threading.Thread(
        target=handle_commands,
        args=(exchange_client,),
        daemon=True
    )
    cmd_thread.start()

    # Mensaje de inicio
    send_telegram_keyboard(
        f"🚀 <b>Crypto Navix AI — Iniciado v2.0</b>\n"
        f"🔬 Modelo: VaR 93% (Z={Z_SCORE_93})\n"
        f"⚡ Par: {SYMBOL} | Apalancamiento: {LEVERAGE}x\n"
        f"💰 VaR máx: ${MAX_VAR_ALLOWED} USDT | Vela: {TIMEFRAME}\n"
        f"{'🟡 Testnet' if IS_TESTNET else '🟢 Mainnet'}\n\n"
        "Usa los botones para consultar el bot:",
        MAIN_KEYBOARD
    )

    logging.info("🏁 Loop de trading iniciado...")

    try:
        while True:
            df = get_data(exchange_client)
            if df is None or df.empty or len(df) < 5:
                logging.warning("⚠️ Datos insuficientes — reintentando en 15s")
                time.sleep(15)
                continue

            current = df.iloc[-1]
            previous = df.iloc[-2]
            price = current["close"]
            var_93 = current["var_93"]
            n_contr = round(BTC_QTY / contract_mult)

            print(f"\n{'─'*60}")
            print(f"🕒 [{datetime.now().strftime('%H:%M:%S')}] {SYMBOL} ${price:,.2f}")
            print(f"📉 VaR 93%: ${var_93:.4f} | Límite: ${MAX_VAR_ALLOWED}")
            print(f"EMA{EMA_SHORT}: {current['ema_fast']:,.2f} | EMA{EMA_LONG}: {current['ema_slow']:,.2f}")
            print(f"RSI: {current['rsi']:.1f} | Posición: {pos_active_type or 'Sin posición'}")

            cross_up = (previous["ema_fast"] < previous["ema_slow"] and
                        current["ema_fast"] > current["ema_slow"])
            cross_down = (previous["ema_fast"] > previous["ema_slow"] and
                          current["ema_fast"] < current["ema_slow"])
            # ─────────────────────────────────────────────────────────────────
            # 🛡️ FILTRO DE RIESGO — COMPUERTA VaR
            # ─────────────────────────────────────────────────────────────────
            risk_ok = var_93 < MAX_VAR_ALLOWED
            # ─────────────────────────────────────────────────────────────────

            # ── Sin posición: buscar entrada ─────────────────────────────────
            if pos_active_type is None:
                if cross_up and risk_ok:
                    fill = place_order(exchange_client, n_contr)
                    if fill:
                        pos_active_type = "LONG"
                        pos_active_size = n_contr
                        pos_entry_price = fill
                        pos_entry_time = datetime.now()
                        trade_history.append({
                            "type": "LONG", "entry_price": fill, "exit_price": None,
                            "size": n_contr, "pnl_usdt": 0.0,
                            "timestamp": pos_entry_time.strftime("%d/%m %H:%M"),
                            "status": "open"
                        })
                        send_telegram(
                            f"🟢 <b>LONG ABIERTO</b>\n"
                            f"Precio: ${fill:,.4f}\n"
                            f"VaR 93%: ${var_93:.4f}\n"
                            f"Contratos: {n_contr}"
                        )

                elif cross_down and risk_ok:
                    fill = place_order(exchange_client, -n_contr)
                    if fill:
                        pos_active_type = "SHORT"
                        pos_active_size = -n_contr
                        pos_entry_price = fill
                        pos_entry_time = datetime.now()
                        trade_history.append({
                            "type": "SHORT", "entry_price": fill, "exit_price": None,
                            "size": n_contr, "pnl_usdt": 0.0,
                            "timestamp": pos_entry_time.strftime("%d/%m %H:%M"),
                            "status": "open"
                        })
                        send_telegram(
                            f"🟣 <b>SHORT ABIERTO</b>\n"
                            f"Precio: ${fill:,.4f}\n"
                            f"VaR 93%: ${var_93:.4f}\n"
                            f"Contratos: {n_contr}"
                        )

            # ── Cierre LONG ──────────────────────────────────────────────────
            elif pos_active_type == "LONG" and cross_down:
                fill = place_order(exchange_client, -pos_active_size)
                if fill:
                    pnl_pct = (fill - pos_entry_price) / pos_entry_price
                    pnl_usdt = round(
                        pnl_pct * pos_active_size * contract_mult *
                        pos_entry_price * int(LEVERAGE), 4
                    )
                    if trade_history:
                        trade_history[-1].update({
                            "exit_price": fill, "pnl_usdt": pnl_usdt, "status": "closed"
                        })
                    e = "🟢" if pnl_usdt >= 0 else "🔴"
                    send_telegram(
                        f"🔴 <b>LONG CERRADO</b>\n"
                        f"Entrada: ${pos_entry_price:,.4f} → Salida: ${fill:,.4f}\n"
                        f"{e} P&L: <b>${pnl_usdt:+.4f} USDT</b>"
                    )
                    pos_active_type = None; pos_active_size = 0
                    pos_entry_price = None; pos_entry_time = None

            # ── Cierre SHORT ─────────────────────────────────────────────────
            elif pos_active_type == "SHORT" and cross_up:
                fill = place_order(exchange_client, -pos_active_size)
                if fill:
                    pnl_pct = (pos_entry_price - fill) / pos_entry_price
                    pnl_usdt = round(
                        pnl_pct * abs(pos_active_size) * contract_mult *
                        pos_entry_price * int(LEVERAGE), 4
                    )
                    if trade_history:
                        trade_history[-1].update({
                            "exit_price": fill, "pnl_usdt": pnl_usdt, "status": "closed"
                        })
                    e = "🟢" if pnl_usdt >= 0 else "🔴"
                    send_telegram(
                        f"🔵 <b>SHORT CERRADO</b>\n"
                        f"Entrada: ${pos_entry_price:,.4f} → Salida: ${fill:,.4f}\n"
                        f"{e} P&L: <b>${pnl_usdt:+.4f} USDT</b>"
                    )
                    pos_active_type = None; pos_active_size = 0
                    pos_entry_price = None; pos_entry_time = None

            time.sleep(60 - (time.time() % 60))

    except KeyboardInterrupt:
        send_telegram("⚠️ <b>Bot Detenido:</b> Interrupción manual (Ctrl+C)")
        logging.info("Bot detenido por el usuario.")
    except Exception as e:
        send_telegram(f"❌ <b>SISTEMA CAÍDO:</b>\n{str(e)}")
        logging.critical(f"Error fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()