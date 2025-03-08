import pandas as pd
import yfinance as yf
import time 
import os 
szTicker = ""
szCompany = ""
szData = ""
szDataCleaned = ""
szDateStart = ""
szDateEnd = ""
szInterval = ""
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
	
	szDateStart = str(input("Enter the date you want the data to start from, in the format 'YYYY-DD-MM':  "))
	if len(szDateStart) == 0:
		print("Can not be empty. Please try again.")
	
	szDateEnd = str(input("Enter the date you want the data to end, in the format 'YYYY-DD-MM':  "))
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
	szDataCleaned["Price Direction"] = (szDataCleaned['Price Change'] > 0).astype(int)
	print("Here is the full sheet of data...")
	time.sleep(1)
	print(szDataCleaned)


MainMenu()