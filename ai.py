import yfinance as yf
import pandas as pd
import xgboost as xgb
from sklearn.preprocessing import StandardScaler as SS
from sklearn.model_selection import train_test_split as tts
from sklearn.model_selection import GridSearchCV 
from sklearn.metrics import accuracy_score


szTicker = "AAPL"

szData = yf.download(szTicker, start="2010-01-01", end="2025-01-01", interval="1d")
szExtraData = yf.download(szTicker, start="1981-01-01", end="2010-01-01")
print(szData)
print(szExtraData)
szData = pd.concat([szExtraData, szData], axis=0)
szData.to_csv("CombinedAPPLDataDay.csv")
print(szData)

szData["Year"] = szData.index.year
szData["Month"] = szData.index.month
szData["Day"] = szData.index.day

szData["Change%"] = ((szData["Close"] - szData["Open"]) / szData["Open"]) * 100

szData["5MA"] = szData["Close"].rolling(window=5).mean()
szData["30MA"] = szData["Close"].rolling(window=30).mean()

szData["Price Movement"] = (szData["Close"].shift(-1) > szData["Close"]).astype(int)
szData["PastClose1"] = szData["Close"].shift(1)
szData["PastClose2"] = szData["Close"].shift(2)
szData["PastClose3"] = szData["Close"].shift(3)

delta = szData["Close"].diff(1)  
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
rsi = 100 - (100 / (1 + rs))
szData["RSI14"] = rsi

szData["12EMA"] = szData["Close"].ewm(span=12, adjust=False).mean()
szData["26EMA"] = szData["Close"].ewm(span=26, adjust=False).mean()
szData["MACD"] = szData["12EMA"] - szData["26EMA"]
szData["SignalLine"] = szData["MACD"].ewm(span=9, adjust=False).mean()

szData.dropna(inplace=True)
scaler = SS()
Columns = ["Open", "High", "Low", "Close", "Volume", "5MA", "30MA", "PastClose1", "PastClose2", "PastClose3", "RSI14", "12EMA", "26EMA", "MACD", "SignalLine"]
szData[Columns] = scaler.fit_transform(szData[Columns])
szData = szData.sort_values(by="Date")
szData.to_csv("ProccesedAPPLDataDay.csv")


print(szData)
szData.sort_index(inplace=True)
X = szData[["Open", "High", "Low", "5MA", "30MA", "PastClose1", "PastClose2", "PastClose3", "Volume", "RSI14", "12EMA", "26EMA", "MACD", "SignalLine"]]
Y = szData["Price Movement"]

X_train, X_test, y_train, y_test = tts(X, Y, test_size=0.2, random_state=42, shuffle=False)
szData.dropna(inplace=True)
param_grid = {
    'n_estimators': [100],
    'max_depth': [36, 48, 60, 70, 100],
    'learning_rate': [0.0001, 0.001, 0.01, 0.1, 5],
    'subsample': [1.0],
    'colsample_bytree': [0.5]
}

xgb_model = xgb.XGBClassifier(objective='binary:logistic', eval_metric='logloss')

grid_search = GridSearchCV(estimator=xgb_model, param_grid=param_grid, cv=50, n_jobs=-1, verbose=2)
grid_search.fit(X_train, y_train)

tuned_model = grid_search.best_estimator_
print("Best Hyperparameters:", grid_search.best_params_)

y_pred = tuned_model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)

y_pred = tuned_model.predict(X_test)
df_results = pd.DataFrame({'Actual': y_test, 'Predicted': y_pred})
print(f"Model Accuracy: {accuracy:.4f}")
print(df_results)
