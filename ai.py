import yfinance as yf 
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


szTicker = "AAPL"
szStartDate = "2000-01-01"
szEndDate = "2025-01-01"

csvData = yf.download(szTicker, start = szStartDate, end = szEndDate)
csvData = csvData[["Open", "High", "Low", "Close"]]
csvData["Prev Close"] = csvData["Close"].shift(1)
csvData["5d Change %"] = csvData["Close"].pct_change(periods = 5) * 100
csvData["10d Change %"] = csvData["Close"].pct_change(periods = 10) * 100
csvData["5d Votality"] = csvData["High"].rolling(window = 5).max() - csvData["Low"].rolling(window = 5).min()

csvData["5d MA"] = csvData["Close"].rolling(window = 5).mean()
csvData["10d MA"] = csvData["Close"].rolling(window = 10).mean()
csvData["30d MA"] = csvData["Close"].rolling(window = 30).mean()

delta = csvData["Close"].diff()
gain = (delta.where(delta > 0, 0)).rolling(window = 14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window = 14).mean()
rs = gain / loss
csvData["RSI"] = 100 - (100 / (1 + rs))
csvData.dropna(inplace = True)
csvData.to_csv("stock_data_features.csv")

X = csvData[["Open", "Prev Close", "5d Change %", "10d Change %", "5d Votality", "5d MA", "10d MA", "30d MA", "RSI"]].values
Y = csvData["Close"]

X_Train, X_Test, Y_Train, Y_Test = train_test_split(X, Y, test_size = 0.2, random_state = 42)
aiModel = RandomForestRegressor(n_estimators=100, random_state = 42)
aiModel.fit(X, Y)
Y_Prediction = aiModel.predict(X_Test)
MAE = mean_absolute_error(Y_Prediction, Y_Test)
MSE = mean_squared_error(Y_Prediction, Y_Test)
r2 = r2_score(Y_Prediction, Y_Test)
print(f"MAE:  {MAE}")
print(f"MSE:  {MSE}")
print(f"r2:  {r2}")
# Print predictions vs actual values
print("Predictions vs Actual Prices (Test Data):")
for i in range(len(Y_Test)):
    print(f"Predicted: {Y_Prediction[i]}, Actual: {Y_Test.iloc[i]}")


predicted_close = aiModel.predict()[0]
print(predicted_close)


