import os
import ta
from sklearn.preprocessing import MinMaxScaler as MMS

szData = []


def CombineData():
	global szData
	df = ""
	FOLDER_PATH = r"D:\Coding\StockMarketAI\StockData"
	OUTPUT_FILE = r"MergedStockData.csv"

	TotalFiles = [Files for Files in os.listdir(FOLDER_PATH)]

	for File in TotalFiles:
		TotalFiles = os.path.join(FOLDER_PATH, File)
		df = pd.read_csv(TotalFiles)
		szData.append(df)
	szData = pd.concat(szData, ignore_index=True)
	szData = szData.sort_values(by="Timestamp")
	szData.to_csv(OUTPUT_FILE, index=False)
	print("Merging complete")

def AddTimestamp():
	global szData
	print(szData)
	szData['Timestamp'] = pd.to_datetime(szData['Timestamp'])

	szData['Year'] = szData['Timestamp'].dt.year
	szData['Month'] = szData['Timestamp'].dt.month
	szData['Day'] = szData['Timestamp'].dt.day
	szData['Hour'] = szData['Timestamp'].dt.hour

	print(szData[['Timestamp', 'Year', 'Month', 'Day', 'Hour']]) 

def ScaleData():
	global szData
	szColums = ""
	
	szColums = ["Open", "High", "Low", "Close", "Volume"]
	Scaler = MMS()
	szData[szColums] = Scaler.fit_transform(szData[szColums])
	print(szData)
	
	

CombineData()
AddTimestamp()
ScaleData()