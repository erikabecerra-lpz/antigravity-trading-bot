import asyncio
import logging
from typing import Dict, Any
import trading_bot_full as bot_core
from features import generate_features
from model import TradingModel
from portfolio import MarkowitzOptimizer
from risk import calculate_risk_metrics
from evaluation import EvaluationModule
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

class TradingBotWrapper:
    def __init__(self):
        self.is_running = False
        self.task = None
        self.exchange_client = None
        self.model = TradingModel()
        self.optimizer = MarkowitzOptimizer()
        self.evaluator = EvaluationModule()
        self.current_portfolio = {}
        self.latest_signals = []
        self.latest_risk = {}
        self.latest_metrics = {}
        self.active_symbols = ['BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'BNB_USDT', 'XRP_USDT'] # Simplificado, idealmente lista dinámica
        
        # Initialize exchange via existing core logic
        try:
            self.exchange_client = bot_core.init_exchange()
            self.contract_mult = bot_core.get_multiplier(self.exchange_client)
        except Exception as e:
            logger.error(f"No se pudo conectar a Gate.io: {e}")

    async def start_bot(self):
        if self.is_running:
            return False
        self.is_running = True
        self.task = asyncio.create_task(self._trading_loop())
        bot_core.send_telegram("🤖 <b>Bot Activado via Web Dashboard</b>\nInicializando ciclo de ML y Optimización...")
        return True

    async def stop_bot(self):
        if not self.is_running:
            return False
        self.is_running = False
        if self.task:
            self.task.cancel()
        bot_core.send_telegram("⏹ <b>Bot Detenido via Web Dashboard</b>")
        return True

    async def _trading_loop(self):
        while self.is_running:
            try:
                logger.info("Iniciando ciclo de trading (ML + Markowitz)...")
                await self._execute_cycle()
            except asyncio.CancelledError:
                logger.info("Trading loop cancelado.")
                break
            except Exception as e:
                logger.error(f"Error en ciclo de trading: {e}")
            
            # Dormir 5 minutos
            await asyncio.sleep(300)

    async def _execute_cycle(self):
        # 1. Obtener datos de yfinance para asegurar suficientes datos para ML
        df_list = []
        for sym in self.active_symbols:
            yf_sym = sym.replace("_USDT", "-USD")
            try:
                df = yf.download(yf_sym, period="5d", interval="15m")
                if not df.empty:
                    df.reset_index(inplace=True)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = [c[0] for c in df.columns]
                    df.rename(columns={'Open':'open', 'High':'high', 'Low':'low', 'Close':'close', 'Volume':'volume'}, inplace=True)
                    # 2. Feature Engineering
                    df_feat = generate_features(df)
                    df_list.append((sym, df_feat))
            except Exception as e:
                logger.error(f"Error descargando datos para {sym}: {e}")
                
        if not df_list:
            return
            
        signals = []
        buy_symbols = []
        returns_dict = {}
        
        for sym, df in df_list:
            # 3. Model Training & Prediction (On-the-fly for simplicity or pre-trained)
            if len(df) > 50:
                self.model.train(df, optimize=False) # Skip gridsearch for speed in live loop
                signal_data = self.model.predict_signal(df, sym)
                signals.append(signal_data)
                if signal_data['signal'] == 'BUY':
                    buy_symbols.append(sym)
                returns_dict[sym] = df['log_return'].values
                
        self.latest_signals = signals
        
        # 4. Markowitz Optimization
        if not buy_symbols: buy_symbols = list(returns_dict.keys())
        if buy_symbols:
            min_len = min(len(v) for v in returns_dict.values())
            returns_df = pd.DataFrame({k: v[-min_len:] for k, v in returns_dict.items()})
            opt_res = self.optimizer.optimize(returns_df, buy_signals=buy_symbols)
            self.current_portfolio = opt_res['weights']
            
            # 5. Risk Management & Execution
            for sym in buy_symbols:
                weight = self.current_portfolio.get(sym, 0)
                if weight > 0:
                    bot_core.SYMBOL = sym
                    current_price = bot_core.get_current_price(self.exchange_client)
                    if current_price:
                        risk = calculate_risk_metrics(sym, current_price, weight * 10000, df_list[0][1]) # 10k nominal
                        self.latest_risk[sym] = risk
                        
                        # EJECUCIÓN CON CORE BOT
                        n_contratos = int((weight * 1000) / current_price / self.contract_mult) if self.contract_mult else 0
                        if n_contratos > 0:
                            bot_core.place_order(self.exchange_client, n_contratos)
                            bot_core.send_telegram(f"🟢 <b>EJECUCIÓN ML: BUY {sym}</b>\nPeso: {weight*100:.1f}% | SL: ${risk.get('stop_loss',0):.2f}")

        # 6. Evaluation
        if df_list:
            min_len = min(len(v) for v in returns_dict.values())
            returns_df = pd.DataFrame({k: v[-min_len:] for k, v in returns_dict.items()})
            report = self.evaluator.generate_report(self.model, self.current_portfolio, returns_df)
            self.latest_metrics = report

# Singleton instance
bot_instance = TradingBotWrapper()
