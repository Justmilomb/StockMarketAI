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


szData["Price Movement"] = (szData["Close"].shift(-1) > szData["Close"])

for i in range(0, 7):
	szData[f"Open_{i}"] = szData["Open"].shift(i)
	szData[f"High_{i}"] = szData["High"].shift(i)
	szData[f"Low_{i}"] = szData["Low"].shift(i)
	szData[f"Close_{i}"] = szData["Close"].shift(i)
	szData[f"Volume_{i}"] = szData["Volume"].shift(i)

szData["Today_Open"] = szData["Open"]
szData.dropna(inplace=True)
X = szData[["Today_Open", "Open_1", "Open_2", "Open_3", "Open_4", "Open_5", "Open_6", "Close_1", "Close_2", "Close_3", "Close_4", "Close_5", "Close_6", "Low_1", "Low_2", "Low_3", "Low_4", "Low_5", "Low_6", "High_1", "High_2", "High_3", "High_4", "High_5", "High_6", "Volume_1", "Volume_2", "Volume_3", "Volume_4", "Volume_5", "Volume_6"]]
Y = szData["Price Movement"]
Scaler = SS()
X_Scaled = Scaler.fit_transform(X)

print(szData)

X_Train, X_Test, Y_Train, Y_Test = tts(X_Scaled, Y, test_size=0.4, shuffle=False, random_state=42)

param_grid = {
    'max_depth': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    'n_estimators': [30],
    'learning_rate': [0.5, 1, 1.5, 2, 2.5, 3],
	'subsample': [0.15, 0.3, ],
	'gamma': [0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1],
	'min_child_weight': [0.5, 0.75, 1],
	'scale_pos_weight': [10, 12, 14, 16, 18, 20]
	}
Model = GridSearchCV(xgb.XGBClassifier(), param_grid, scoring="accuracy", cv=25, verbose=2, n_jobs=-1)
Model.fit(X_Train, Y_Train)

Y_Pred = Model.predict(X_Test)
Accuracy = accuracy_score(Y_Test, Y_Pred)

print(f"Model accuracy: {Accuracy:.4f}")
print("Best parameters: ", Model.best_params_)
