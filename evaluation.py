import pandas as pd
import numpy as np

class EvaluationModule:
    def __init__(self):
        self.history = []
        self.initial_capital = 10000.0
        
    def generate_report(self, model_instance, portfolio_weights, prices_df: pd.DataFrame):
        """
        Genera un reporte consolidado con métricas de evaluación del modelo y simulación de ROI.
        """
        report = {}
        
        # 1. Hiperparámetros y métricas de modelo (desde model_instance)
        report['hyperparameters'] = model_instance.best_params_ if model_instance.best_params_ else {}
        report['metrics'] = model_instance.metrics_
        
        # 2. Confusion Matrix (desde model_instance)
        if 'confusion_matrix' in model_instance.metrics_:
            report['confusion_matrix'] = model_instance.metrics_['confusion_matrix']
            
        # 3. Feature Importance
        if model_instance.feature_importances_:
            importance_data = []
            for i, name in enumerate(model_instance.feature_names_):
                importance_data.append({
                    'feature': name,
                    'importance': float(model_instance.feature_importances_[i])
                })
            # Ordenar descendente
            importance_data.sort(key=lambda x: x['importance'], reverse=True)
            report['feature_importance'] = importance_data
            
        # 4. ROI Simulado (Equity curve básica)
        # Asumimos que prices_df contiene columnas de log_returns de los activos.
        # Simulamos la aplicación de los pesos en la última ventana disponible.
        # Retorno del portafolio = Sum(pesos * retornos)
        equity_curve = [self.initial_capital]
        current_capital = self.initial_capital
        
        if not prices_df.empty and portfolio_weights:
            # Calculamos retorno ponderado por fila
            weighted_returns = pd.Series(0.0, index=prices_df.index)
            for symbol, weight in portfolio_weights.items():
                col_name = symbol
                if col_name in prices_df.columns:
                    weighted_returns += prices_df[col_name] * weight
                    
            # Transformar log return a simple return para cálculo de capital
            simple_returns = np.exp(weighted_returns) - 1
            
            for ret in simple_returns.dropna():
                current_capital *= (1 + ret)
                equity_curve.append(float(current_capital))
                
        report['roi_simulado'] = {
            'initial_capital': self.initial_capital,
            'final_capital': current_capital,
            'roi_pct': ((current_capital - self.initial_capital) / self.initial_capital) * 100,
            'equity_curve': equity_curve
        }
        
        return report
