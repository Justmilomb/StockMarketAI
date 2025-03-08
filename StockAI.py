import pandas as pd
import yfinance as yf
import time 
import os 
szTicker = ""
szCompany = ""
szData = ""
iMissingData = 0
szDataCleaned = ""
szDateStart = ""
szDateEnd = ""

def MainMenu():
	global szTicker, szDateStart, szDateEnd
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
	

	LoadData()
	
	
def LoadData():
	global szTicker, szDateStart, szDateEnd
	ClearTerminal()
	szCompany = yf.Ticker(szTicker)
	szData = szCompany.history(interval="1d", start=str(szDateStart), end=str(szDateEnd))
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
	print("Here is the full sheet of data...")
	time.sleep(1)
	print(szDataCleaned)
	

	
def ClearTerminal():
	if os.name == "nt":
		os.system("cls")
	else:
		os.system("clear")


MainMenu()