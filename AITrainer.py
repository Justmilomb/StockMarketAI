import pandas as pd #
import yfinance as yf # The api for the stock market data from 'Yahoo Finance'
import time # Used for genral usability
import os # Used for genral usability
import matplotlib.pyplot as plt # Used to make a graph with the stock data
from sklearn.preprocessing import StandardScaler as ss # This scales down all the selected data in szColumns
from sklearn.ensemble import RandomForestClassifier as rfc # This is the ai trainer
from sklearn.model_selection import RandomizedSearchCV as rs # Finds the right paramaters for 'rfc'
from sklearn.model_selection import train_test_split as tts # Splits the selected data into 'train' and 'test' data
import joblib as jl # Used to save the ai to a file on the local computer

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
szSaveAi = ""
szAiName = ""
best_model = ""
szColumns = ""
szScaledown = ""
szTraining = ""
szNewGraph = ""


def ClearTerminal():
	if os.name == "nt":
		os.system("cls") # Used for windows computer
	else:
		os.system("clear") # Used for other compters

	
def MainMenu():
	global szTicker, szDateStart, szDateEnd, szDataCleaned, szInterval
	ClearTerminal()
	print("Lets train a stock market ai:  ")
	time.sleep(0.5)
	
	while len(szTicker) == 0:																											
		szTicker = input("Enter the 'ticker' code for the company you want to track:  ").strip().upper()							# Enter the 'Ticker' code PS. Code does not yet understand if Ticker code is genuine or not
		if len(szTicker) == 0:																										# Program will crash eventually and not work how wanted
			print("Can not be empty. Please try again.")
		
	while len(szDateStart) == 0:
		szDateStart = str(input("Enter the date you want the data to start from, in the format 'YYYY-MM-DD':  ")).strip()			# Enter the 'Starting Date' code PS. Code does not yet understand if starting date is genuine or not
		if len(szDateStart) == 0:																									# Program will crash eventually and not work how wanted
				print("Can not be empty. Please try again.")
		
	while len(szDateEnd) == 0:
		szDateEnd = str(input("Enter the date you want the data to end, in the format 'YYYY-MM-DD':  ")).strip()					# Enter the 'Ending Date' code PS. Code does not yet understand if ending date is correct or not
		if len(szDateEnd) == 0:																										# Program will crash eventually and not work how wanted
			print("Can not be empty. Please try again.")
		
	
	while len(szInterval) == 0:
		szInterval = str(input("Enter the interval you would like.\nPossible intervals are '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1d', '5d', '1wk', '1mo', '3m'\nPS.Interday options are only availabe for past seven days:  ")).strip().lower()				# Enter the 'Interval' code PS. Code does not yet understand if Interval is correct or not
		if szInterval == 0:																																																												# Program will crash eventually and not work how wanted																																			
			print("Can not be empty. Please try again.")
			print("Loading data...")
	LoadData()	
			
	
	
			
	
	
def LoadData():
	global szTicker, szDateStart, szDateEnd, szDataCleaned, szInterval, szSaveAi, szAiName, best_model, szScaledown, szTraining, szNewGraph
	ClearTerminal()
	szCompany = yf.Ticker(szTicker) # The 'ticker' picked earlier is assigned to 'szCompany'
	szData = szCompany.history(interval=str(szInterval), start=str(szDateStart), end=str(szDateEnd)) # Applies inputed data from user inputs into 'szData' to get yahoo finance stock information 
	pd.set_option("display.max_rows", None) # Shows all the rows of data
	pd.set_option("display.max_columns", None) # Shows all columns of data
	pd.set_option("display.width", 1000) # Makes sure proportions of the graph stay correct
	szData.isnull().sum() # Gets rid of empty pulled data from yahoo finnance
	print("Getting rid of missing data...") 
	# show fake loading progress bar
	time.sleep(2) # Temporary replacment for progress bar
	szDataCleaned = szData.dropna() # Makes sure 'no number' data is taken from 'szData' and effectively cleans it
	szDataCleaned["Price Change"] = szDataCleaned["Close"].diff() # Calculates price change and makes new column on 'szDataCleaned'
	szDataCleaned["Price Direction"] = (szDataCleaned["Close"] > szDataCleaned["Open"]).astype(int) # Calculates if price is going down or up (0 or 1) and creates new column on 'szDataCleaned'
	szDataCleaned["7-Day MA"] = szDataCleaned["Close"].rolling(window=7).mean() # Calculates 7-Day Average of prices and creates new column on 'szDataCleaned'
	szDataCleaned["30-Day MA"] = szDataCleaned["Close"].rolling(window=30).mean() # Calculates 30-Day Average of prices and creates new column on 'szDataCleaned'
	szDataCleaned = szDataCleaned.dropna() # Because of the averages some data to start will have 'no number' data and we have to clear the rows
	print("Here is the full sheet of data...")
	# show fake loading progress bar
	time.sleep(2) # Temporary replacment for progress bar
	print(szDataCleaned)
	
	while len(szNewGraph) == 0:
		szNewGraph = input("Would you like a graph to visualize the data for anomilies? 'y' or 'n':  ").strip().lower()
		if len(szNewGraph) == 0:
			print("Input can not be empty")
			time.sleep(0.5)
			print("Try again")
			time.sleep(1.5)
		elif szNewGraph == "y":
			print("Producing a graph...")
			time.sleep(3) # Replace with progress bar
			NewGraph()
		elif szNewGraph == "n":
			print("Skipping making the graph")
		else:
			szNewGraph = ""
			print("Incorrect input try again...")
			time.sleep(1.5)
		

	
	while len(szScaledown) == 0:
		szScaledown = input("Do you want to scale down the data for better ai training? 'y' or 'n':  ").strip().lower()
		if len(szScaledown) == 0:
			print("Input can not be empty")
			time.sleep(0.5)
			print("Try again")
			time.sleep(1.5)
		elif szScaledown == "y":
			print("Scaling the data down for better use...") 
			time.sleep(3) # Replace with progress bar 
			ScaleDown()
		elif szScaledown == "n":
			print("Skipping the scaling down")
		else:
			szScaledown = ""
			print("Incorrect input try again...")
			time.sleep(1.5)
		
		
	while len(szTraining) == 0:
		szTraining = input("Do you want to start training the ai on the data? 'y' or 'n':  ").strip().lower()
		if len(szTraining) == 0:
			print("Input can not be empty")
			time.sleep(0.5)
			print("Try again")
			time.sleep(1.5)
		elif szScaledown == "y":
			print("Starting Training now")
			time.sleep(3) # Replace with progress bar
			Training() 
		elif szTraining == "n":
			print("Skipping the ai training")
		else:
			szTraining = ""
			print("Incorrect input try again...")
			time.sleep(1.5)
		
	while len(szSaveAi) == 0:
		szSaveAi = input("Would you like to save this trained ai? 'y' or 'n':  ").strip().lower()
		if len(szSaveAi) == 0:
			print("Input can not be empty")
			time.sleep(0.5)
			print("Try again")
			time.sleep(1.5)
		elif szSaveAi == "y":
				while len(szAiName) == 0:
					szAiName = input("What will the ai be called?:  ").strip()
					if len(szAiName) == 0:
						print("Input can not be empty")
						time.sleep(0.5)
						print("Try again")
						time.sleep(1.5)
					elif len(szAiName) != 0:
						print("Saving ai now...")
						time.sleep(3) # Replace with progress bar
						jl.dump(best_model, f"{szAiName}.pkl") # Saves model under specific user set name 
						print("Model now saved")
					
		elif szSaveAi == "n":
			print("Skipping saving the ai")
		else:
			szSaveAi = ""
			print("Incorrect input try again...")
			time.sleep(1.5)
			
	
	
	

def NewGraph():
	global szDataCleaned 
	plt.figure(figsize=(10,6))
	plt.plot(szDataCleaned.index, szDataCleaned["Close"], label = "Closing Price", color = "blue")
	plt.plot(szDataCleaned.index, szDataCleaned["7-Day MA"], label = "7-Day MA", color = "green")
	plt.plot(szDataCleaned.index, szDataCleaned["30-Day MA"], label = "30-Day MA", color = "red")
	plt.xlabel("Date")
	plt.ylabel("Price in USD")
	plt.title("Stock prices and moving averages")
	print("Please close and save (if wanted) the graph to continue the program")
	plt.legend()
	plt.show()
	

def ScaleDown():
	global szDataCleaned, szColumns
	szColumns = ["Open", "Close", "High", "Low", "Volume", "Price Change"]
	Scaler = ss()
	szDataCleaned[szColumns] = Scaler.fit_transform(szDataCleaned[szColumns])
	print(szDataCleaned)

def Training():
	ClearTerminal()
	global szX, szY, szDataCleaned, best_model
	szX = szDataCleaned[["Open", "Close", "High", "Low", "Volume", "Price Change"]]
	szY = szDataCleaned["Price Direction"]
	szX_train, szX_test, szY_train, szY_test = tts(szX, szY, test_size=0.3, random_state=42)
	model = rfc(random_state=42, n_jobs=-1)
	param_grid ={'n_estimators': [100], 
				'max_depth': [400],  
				'min_samples_split': [800],
				'min_samples_leaf': [60]}			

	grid_search = rs(model, param_grid, cv=50, scoring='accuracy', verbose=1, n_jobs=-1)
	grid_search.fit(szX_train, szY_train)
	best_model = grid_search.best_estimator_
	print("Best model parameters:", grid_search.best_params_)
	print("Training accuracy:", best_model.score(szX_train, szY_train))
	print("Testing accuracy:", best_model.score(szX_test, szY_test))




MainMenu()