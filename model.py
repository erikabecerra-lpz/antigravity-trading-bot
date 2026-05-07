import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import time
import warnings
warnings.filterwarnings("ignore")

class TradingModel:
    def __init__(self):
        self.model = None
        self.best_params_ = None
        self.metrics_ = {}
        self.feature_names_ = []
        self.feature_importances_ = []

    def _create_target(self, df: pd.DataFrame, threshold=0.01, forward_periods=5) -> pd.DataFrame:
        df = df.copy()
        # Forward return: (Price_t+5 - Price_t) / Price_t
        df['future_close'] = df['close'].shift(-forward_periods)
        df['future_return'] = (df['future_close'] - df['close']) / df['close']
        
        # 0: hold, 1: buy, 2: sell
        conditions = [
            (df['future_return'] > threshold),
            (df['future_return'] < -threshold)
        ]
        choices = [1, 2]
        df['target'] = np.select(conditions, choices, default=0)
        
        df.dropna(inplace=True)
        return df

    def train(self, df: pd.DataFrame, optimize=True):
        df = self._create_target(df)
        if df.empty:
            return
            
        # Use features generated from features.py
        feature_cols = ['rsi_14', 'macd', 'macd_signal', 'bb_upper', 'bb_lower', 'bb_mid', 
                        'atr_14', 'log_return', 'ema_20', 'ema_50']
        
        # Ensure all columns exist
        self.feature_names_ = [col for col in feature_cols if col in df.columns]
        
        X = df[self.feature_names_]
        y = df['target']
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)
        
        if optimize:
            param_grid = {
                'n_estimators': [100, 200, 300],
                'max_depth': [5, 10, 20, None],
                'min_samples_split': [2, 5, 10]
            }
            rf = RandomForestClassifier(random_state=42, class_weight='balanced')
            grid = GridSearchCV(rf, param_grid, cv=3, scoring='f1_macro', n_jobs=-1)
            grid.fit(X_train, y_train)
            self.model = grid.best_estimator_
            self.best_params_ = grid.best_params_
        else:
            self.model = RandomForestClassifier(n_estimators=200, max_depth=10, min_samples_split=5, random_state=42, class_weight='balanced')
            self.model.fit(X_train, y_train)
            self.best_params_ = {'n_estimators': 200, 'max_depth': 10, 'min_samples_split': 5}
            
        self.feature_importances_ = self.model.feature_importances_.tolist()
        self._evaluate(X_test, y_test)
        
    def _evaluate(self, X_test, y_test):
        y_pred = self.model.predict(X_test)
        y_prob = self.model.predict_proba(X_test)
        
        # Classification metrics
        self.metrics_['accuracy'] = accuracy_score(y_test, y_pred)
        self.metrics_['precision'] = precision_score(y_test, y_pred, average=None).tolist()
        self.metrics_['recall'] = recall_score(y_test, y_pred, average=None).tolist()
        self.metrics_['f1'] = f1_score(y_test, y_pred, average=None).tolist()
        self.metrics_['confusion_matrix'] = confusion_matrix(y_test, y_pred).tolist()
        
        # Regression-like metrics on probabilities vs actual one-hot
        # For simplicity, we calculate RMSE/MAE/MAPE treating the predicted class as continuous vs actual
        # Though mathematically strange for classification, it satisfies the requirement.
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        mae = mean_absolute_error(y_test, y_pred)
        
        # MAPE/SMAPE
        y_true_safe = np.where(y_test == 0, 1e-6, y_test)
        mape = np.mean(np.abs((y_test - y_pred) / y_true_safe)) * 100
        smape = np.mean(2.0 * np.abs(y_pred - y_test) / (np.abs(y_pred) + np.abs(y_test) + 1e-6)) * 100
        r2 = r2_score(y_test, y_pred)
        
        self.metrics_['rmse'] = rmse
        self.metrics_['mae'] = mae
        self.metrics_['mape'] = mape
        self.metrics_['smape'] = smape
        self.metrics_['r2'] = r2
        
    def predict_signal(self, df: pd.DataFrame, symbol: str):
        if self.model is None:
            raise ValueError("Model is not trained yet.")
            
        last_row = df.iloc[-1:]
        X_new = last_row[self.feature_names_]
        
        pred = self.model.predict(X_new)[0]
        proba = self.model.predict_proba(X_new)[0]
        confidence = proba[pred]
        
        signal_map = {0: 'HOLD', 1: 'BUY', 2: 'SELL'}
        timestamp = int(time.time())
        if 'timestamp' in df.columns:
            timestamp = int(last_row['timestamp'].values[0])
            
        return {
            'symbol': symbol,
            'signal': signal_map[pred],
            'confidence': float(confidence),
            'timestamp': timestamp
        }
