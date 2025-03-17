import joblib
import numpy as np
import yfinance as yf
import datetime
from sklearn.preprocessing import StandardScaler as SS

LoadedModel = joblib.load("stock_model.pkl")
LoadedScaler = joblib.load("scaler.pkl")

szTicker = input("Enter the ticker code:  ").strip().upper()
szYesterday = input("Enter todays date:  ").strip()
szOpenToday = input("Enter todays open price:  ").strip()

dtPast = datetime.datetime.strptime(szYesterday, "%Y-%m-%d")
dtStart = dtPast - datetime.timedelta(days=50)

szData = yf.download(szTicker, start=dtStart.strftime("%Y-%m-%d"), end=dtPast.strftime("%Y-%m-%d"))
print(szData)
szData["Year"] = szData.index.year
szData["Month"] = szData.index.month
szData["Day"] = szData.index.day


szData["Price Movement"] = (szData["Close"].shift(-1) > szData["Close"].astype(int))

for i in range(0, 7):
	szData[f"Open_{i}"] = szData["Open"].shift(i)
	szData[f"High_{i}"] = szData["High"].shift(i)
	szData[f"Low_{i}"] = szData["Low"].shift(i)
	szData[f"Close_{i}"] = szData["Close"].shift(i)
	szData[f"Volume_{i}"] = szData["Volume"].shift(i)


szData.loc[szData.index[-1], "Today_Open"] = float(szOpenToday)

szData.dropna(inplace=True)
X = szData[["Today_Open", "Open_1", "Open_2", "Open_3", "Open_4", "Open_5", "Open_6", "Close_1", "Close_2", "Close_3", "Close_4", "Close_5", "Close_6", "Low_1", "Low_2", "Low_3", "Low_4", "Low_5", "Low_6", "High_1", "High_2", "High_3", "High_4", "High_5", "High_6", "Volume_1", "Volume_2", "Volume_3", "Volume_4", "Volume_5", "Volume_6"]]
Y = szData["Price Movement"]
Scaler = SS()
X_Scaled = Scaler.fit_transform(X)
szData.to_csv("CombinedSDSDDAPPLDataDay.csv")
print(X_Scaled)

szInput = X_Scaled
szPrediction = LoadedModel.predict(szInput)[0]
print(f"Predicted Price Movement: {'Up' if szPrediction == 1 else 'Down'}")
