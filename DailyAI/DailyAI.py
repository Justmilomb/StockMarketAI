import requests
import pandas as pd
import time 
import os

API_KEY = "ZH9X5NIRXZGZPJ3O"
TICKER = "AAPL"
INTERVAL = "1min"
OUTPUT_SIZE = "full"  # "compact" for last 100 data points, "full" for full history
OutputFolder = "StockData"
os.makedirs(OutputFolder, exist_ok=True)

for year in range(2000, 2025 + 1):
	for month in range(1, 13 + 1)
		szDataStart = F"{year}-{month:02d}"
		URL = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={TICKER}&interval={INTERVAL}&outputsize={OUTPUT_SIZE}&apikey={API_KEY}&month={szDataStart}"

		response = requests.get(URL)
		data = response.json()

# Convert to DataFrame
		df = pd.DataFrame(data["Time Series (1min)"])
		df.columns = ["open", "high", "low", "close", "volume"]
		df.index = pd.to_datetime(df.index)

# Save to CSV
		df.to_csv("apple_stock_minute_data.csv")
		print("Data saved successfully!")
