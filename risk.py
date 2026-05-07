import numpy as np
import pandas as pd

def calculate_risk_metrics(symbol: str, entry_price: float, position_size: float, df: pd.DataFrame):
    """
    Calcula métricas de riesgo para una posición abierta usando datos históricos recientes.
    df debe contener las columnas generadas en features.py (atr_14, log_return)
    """
    if df.empty or 'atr_14' not in df.columns or 'log_return' not in df.columns:
        return {}
        
    last_row = df.iloc[-1]
    atr = last_row['atr_14']
    
    # Stop Loss y Take Profit
    stop_loss = entry_price - (2 * atr)
    take_profit = entry_price + (3 * atr)
    
    # Volatilidad (std de los últimos 20 periodos de log_return)
    recent_returns = df['log_return'].tail(20)
    volatility = recent_returns.std()
    
    # VaR 95% (percentil 5 de log-returns historicos * posición en USDT)
    # position_size asume valor nocional en USDT
    var_95_percentile = np.percentile(df['log_return'].dropna(), 5)
    var_95 = abs(var_95_percentile * position_size)
    
    return {
        'symbol': symbol,
        'entry_price': float(entry_price),
        'stop_loss': float(stop_loss),
        'take_profit': float(take_profit),
        'atr': float(atr),
        'volatility': float(volatility),
        'var_95': float(var_95)
    }
