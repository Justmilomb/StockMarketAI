
# Imports
import time
import os
import pandas as pd
import requests
from io import StringIO


def ClearTerminal():
	if os.name == "nt":
		os.system("cls") # Used for windows computer
	else:
		os.system("clear") # Used for other compters
		
	
def MainMenu():
	szAnswer1 = ""
	ClearTerminal()
	print("Lets go train a stock market ai!")
	time.sleep(1)
	print("PS. Did you change the source code to you're desired settings in the 'LoadData' function on line 57?:  ")
	time.sleep(0.5)
	while len(szAnswer1) == 0:
		szAnswer1 = input("Have you? 'y' or 'n':  ").strip().lower()
		if szAnswer1 == "y":
			print("Ok then lets get started...")
			time.sleep(3) # Temporary replacment for progress bar
			LoadData()
		elif szAnswer1 == "n":
			print("You better go change it then...")
			time.sleep(1.5)
			quit()
		else:
			szAnswer1 = ""
			print("Incorrect input try again...")
			time.sleep(1.5)
	
	
def LoadData():
	
	szAnswer1 = ""
	szURL = ""
	szData = ""
	szDataNice = ""
	szCOMPANY = "AAPL"
	szINTERVAL = "1min"
	szOUT_PUT_SIZE = "full"
	szAPI_KEY = "ZH9X5NIRXZGZPJ3O"
	szDATA_START = "2024-01"

	szURL = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={szCOMPANY}&interval={szINTERVAL}&outputsize={szOUT_PUT_SIZE}&apikey={szAPI_KEY}&month={szDATA_START}&datatype=csv"
	Response = requests.get(szURL)
	csv_data = StringIO(Response.text)
	szData = pd.read_csv(csv_data)
	szData['Timestamp'] = pd.to_datetime(szData['timestamp'])
	szDataNice = pd.DataFrame(szData)
	szDataNice.columns = ["Timestap", "Open", "High", "Close", "Low", "Close", "Volume"]
	print("Printing data for you...")
	time.sleep(3) # Temporary replacment for progress bar
	print(szDataNice)
	while len(szAnswer1) == 0:
		szAnswer1 = input("Would you like to save this data? 'y' or 'n':   ").strip().lower()
		if szAnswer1 == "y":
			print("Saving now...")
			time.sleep(3) # Temporary replacment for progress bar
			szDataNice.to_csv("apple_stock_minute_data.csv")
			print("Data saved successfully!")
		elif szAnswer1 == "n":
			print("Skipping saving the ai...")
			time.sleep(1)
		else:
			szAnswer1 = ""
			print("Invalid input try again...")
			time.sleep(1.5)
	
	



MainMenu()