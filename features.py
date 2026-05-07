import pandas as pd
import pandas_ta as ta
import numpy as np

def generate_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Genera las features técnicas para un DataFrame OHLCV utilizando pandas_ta.
    Asume que el DataFrame tiene columnas 'open', 'high', 'low', 'close', 'volume'.
    """
    df = df.copy()
    
    # Asegurar que las columnas existan en lowercase
    cols_lower = {c: c.lower() for c in df.columns}
    df.rename(columns=cols_lower, inplace=True)
    
    if not all(col in df.columns for col in ['open', 'high', 'low', 'close']):
        raise ValueError("El DataFrame debe contener las columnas 'open', 'high', 'low' y 'close'")

    # RSI 14
    df.ta.rsi(length=14, append=True)
    df.rename(columns={'RSI_14': 'rsi_14'}, inplace=True)
    
    # MACD (12, 26, 9)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.rename(columns={
        'MACD_12_26_9': 'macd',
        'MACDs_12_26_9': 'macd_signal'
    }, inplace=True)
    
    # Bollinger Bands (20, 2σ)
    df.ta.bbands(length=20, std=2, append=True)
    df.rename(columns={
        'BBL_20_2.0': 'bb_lower',
        'BBM_20_2.0': 'bb_mid',
        'BBU_20_2.0': 'bb_upper'
    }, inplace=True)
    
    # ATR 14
    df.ta.atr(length=14, append=True)
    df.rename(columns={'ATRr_14': 'atr_14'}, inplace=True)
    
    # Log Return
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    
    # EMA 20 y EMA 50
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.rename(columns={
        'EMA_20': 'ema_20',
        'EMA_50': 'ema_50'
    }, inplace=True)
    
    # Limpiar posibles NaNs generados por los indicadores (ej: primeras N velas)
    df.dropna(inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    return df
