import numpy as np
import pandas as pd
from scipy.optimize import minimize

class MarkowitzOptimizer:
    def __init__(self, risk_free_rate=0.0):
        self.risk_free_rate = risk_free_rate
        self.weights_ = {}
        self.sharpe_ratio_ = 0.0
        self.efficient_frontier_ = []

    def optimize(self, log_returns_df: pd.DataFrame, buy_signals: list):
        """
        log_returns_df: DataFrame donde cada columna es un activo y las filas son los retornos logarítmicos.
        buy_signals: lista de símbolos (columnas) que tienen señal de BUY.
        """
        if not buy_signals:
            return {'weights': {}, 'sharpe_ratio': 0, 'efficient_frontier': []}
            
        # Filtrar solo activos con señal de compra
        valid_assets = [s for s in buy_signals if s in log_returns_df.columns]
        if not valid_assets:
            return {'weights': {}, 'sharpe_ratio': 0, 'efficient_frontier': []}
            
        returns = log_returns_df[valid_assets]
        num_assets = len(valid_assets)
        
        if num_assets == 1:
            # Si solo hay 1 activo con compra, peso 100%
            mean_ret = returns.mean().values[0] * 252 * 1440 # Asumiendo velas de 1m, aproximamos a anual
            volatility = returns.std().values[0] * np.sqrt(252 * 1440)
            sharpe = (mean_ret - self.risk_free_rate) / (volatility if volatility > 0 else 1e-6)
            return {
                'weights': {valid_assets[0]: 1.0},
                'sharpe_ratio': float(sharpe),
                'efficient_frontier': [{'return': float(mean_ret), 'volatility': float(volatility)}]
            }
            
        # Anualizar (Asumiendo temporalidad de 1 día, si es 1m multiplicar por 1440*365)
        # Se usará factor 365 asumiendo crypto diaria por simplicidad, o 1 si ya son periodos relativos.
        # Para este dashboard usaremos factor diario (365) sobre retornos diarios (60 dias requeridos)
        annualization_factor = 365
        
        mean_returns = returns.mean() * annualization_factor
        cov_matrix = returns.cov() * annualization_factor
        
        # Objetivo: Minimizar Volatilidad (Varianza)
        def portfolio_variance(weights):
            return np.dot(weights.T, np.dot(cov_matrix, weights))
            
        def portfolio_return(weights):
            return np.sum(mean_returns * weights)
            
        # Restricciones
        constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})
        bounds = tuple((0, 1) for _ in range(num_assets))
        
        # Punto inicial: igual ponderación
        init_guess = num_assets * [1. / num_assets,]
        
        # Optimización SLSQP
        opt_result = minimize(portfolio_variance, init_guess, method='SLSQP', bounds=bounds, constraints=constraints)
        
        optimal_weights = opt_result.x
        opt_return = portfolio_return(optimal_weights)
        opt_volatility = np.sqrt(opt_result.fun)
        opt_sharpe = (opt_return - self.risk_free_rate) / opt_volatility if opt_volatility > 0 else 0
        
        # Generar Frontera Eficiente (Monte Carlo - 500 portafolios)
        simulated_portfolios = []
        for _ in range(500):
            weights = np.random.random(num_assets)
            weights /= np.sum(weights)
            p_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            p_return = np.sum(mean_returns * weights)
            simulated_portfolios.append({
                'return': float(p_return),
                'volatility': float(p_volatility)
            })
            
        self.weights_ = {valid_assets[i]: float(optimal_weights[i]) for i in range(num_assets)}
        self.sharpe_ratio_ = float(opt_sharpe)
        self.efficient_frontier_ = simulated_portfolios
        
        return {
            'weights': self.weights_,
            'sharpe_ratio': self.sharpe_ratio_,
            'efficient_frontier': self.efficient_frontier_
        }
