import pandas as pd
import yfinance as yf
import time 
import os 
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler as ss
from sklearn.ensemble import RandomForestRegressor as rfr
from sklearn.model_selection import GridSearchCV as gs
from sklearn.model_selection import train_test_split as tts
from tqdm import tqdm

szTicker = ""
szCompany = ""
szCompany = ""
szCompany = ""
szData = ""
szDataCleaned = ""
szDateStart = ""
szDateEnd = ""
szInterval = ""
szX = ""
szY = ""
iMissingData = 0


def ClearTerminal():
	if os.name == "nt":
		os.system("cls")
	else:
		os.system("clear")


def MainMenu():
	global szTicker, szDateStart, szDateEnd, szDataCleaned, szInterval
	ClearTerminal()
	print("Lets train a stock market ai:  ")
	time.sleep(0.5)
	szTicker = str(input("Enter the 'ticker' code for the company you want to track:  ")).strip().upper()
	if len(szTicker) == 0:
		print("Can not be empty. Please try again.")
	
	szDateStart = str(input("Enter the date you want the data to start from, in the format 'YYYY-MM-DD':  ")).lower()
	if len(szDateStart) == 0:
		print("Can not be empty. Please try again.")
	
	szDateEnd = str(input("Enter the date you want the data to end, in the format 'YYYY-MM-DD':  ")).lower()
	if len(szDateEnd) == 0:
		print("Can not be empty. Please try again.")

	szInterval = str(input("Enter the interval you would like.\nPossible intervals are '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1d', '5d', '1wk', '1mo', '3m'\n                     PS.Interday options are only availabe for past seven days:  ")).strip().lower()
	if len(szInterval) == 0:
		print("Can not be empty. Please try again.")

	

	LoadData()
	
	
def LoadData():
	global szTicker, szDateStart, szDateEnd, szDataCleaned, szInterval
	ClearTerminal()
	szCompany = yf.Ticker(szTicker)
	szData = szCompany.history(interval=str(szInterval), start=str(szDateStart), end=str(szDateEnd))
	pd.set_option("display.max_rows", None)
	pd.set_option("display.max_columns", None)
	pd.set_option("display.width", 1000)
	iMissingData = szData.isnull().sum()
	print("First lets see the missing data...")
	time.sleep(1)
	print(f"Missing data is loading...")
	time.sleep(1)
	print(iMissingData)
	szDataCleaned = szData.dropna()
	szDataCleaned["Price Change"] = szDataCleaned["Close"].diff() 
	szDataCleaned["Price Direction"] = (szDataCleaned["Price Change"] > 0).astype(int)
	szDataCleaned["7-Day MA"] = szDataCleaned["Close"].rolling(window=7).mean()
	szDataCleaned["30-Day MA"] = szDataCleaned["Close"].rolling(window=30).mean()
	szDataCleaned = szDataCleaned.dropna()
	print("Here is the full sheet of data...")
	time.sleep(3)
	print(szDataCleaned)
	print("Scaling the data down for better use...")
	time.sleep(3)
	ScaleDown()
	print("Starting Training...")
	time.sleep(3)
	Training()
	

def LoadGraph():
	global szDataCleaned
	plt.figure(figsize=(10,6))
	plt.plot(szDataCleaned.index, szDataCleaned["Close"], label = "Closing Price", color = "blue")
	plt.plot(szDataCleaned.index, szDataCleaned["7-Day MA"], label = "7-Day MA", color = "green")
	plt.plot(szDataCleaned.index, szDataCleaned["30-Day MA"], label = "30-Day MA", color = "red")
	plt.xlabel("Date")
	plt.ylabel("Price in USD")
	plt.title("Stock prices and moving averages")
	plt.legend()
	plt.show()
	print("Starting Training...")
	time.sleep(3)
	Training()
	

def ScaleDown():
	global szDataCleaned
	Columns = ["Close", "7-Day MA", "30-Day MA"]
	Scaler = ss()
	szDataCleaned[Columns] = Scaler.fit_transform(szDataCleaned[Columns])
	print(szDataCleaned)

def Training():
	ClearTerminal()
	global szX, szY, szDataCleaned
	szX = szDataCleaned[["Close", "7-Day MA", "30-Day MA"]]
	szY = szDataCleaned["Price Direction"]
	szX_train, szX_test, szY_train, szY_test = tts(szX, szY, test_size=0.2, random_state=42)
	model = rfr(random_state=42)
	param_grid ={'n_estimators': [100, 200, 300, 400, 500, 600, 700, 800], 
				'max_depth': [20, 30, 40, 50, 60, 70],  
				'min_samples_split': [2, 5, 10, 15, 20, 30, 40],
				'min_samples_leaf': [1, 2, 4]}			

	grid_search = gs(model, param_grid, cv=5, scoring='r2', verbose=1)
	grid_search.fit(szX_train, szY_train)
	best_model = grid_search.best_estimator_
	print("Best model parameters:", grid_search.best_params_)
	print("Training r:", best_model.score(szX_train, szY_train))
	print("Testing r:", best_model.score(szX_test, szY_test))




MainMenu()