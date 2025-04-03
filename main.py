import json
from Adafruit_GPIO import GPIO
from Interfaces import RotaryEncoder, ADS1115, MenuControls

#set default values for plant pot for the event of missing or corrupted config.json file
defaulttimer = 100
defaultwateringamount = 50
defaultmoisturemax = 30

#jasonfile config read or write of defaul values if json file is corrupted or missing --> writing of config data into global variables
def jsonfiledefault():      #if json file was missing this function is used for debugging and notifications
    print("config file was empty or missing, default values were added")
try:                                        #opening json file conifg.json to read all content and write it to data for later extraction
    with open('config.json', 'r+') as f:
        data = json.load(f)
        print("config file successfully opened and read")
except:
    with open('config.json', 'w+') as f:    #if json file is empty or missing a new file is created and default values are added
        data = [{"timer":defaulttimer, "moisturemax":defaultmoisturemax, "wateringamount":defaultwateringamount}]
        json.dump(data, f, indent=4)
        jsonfiledefault()
timer = data[0]['timer']                    #Global Variable for Timer
wateringamount = data[0]['wateringamount']  #Global Variable for wateringamount
moisturemax = data[0]['moisturemax']        #Global Variable for moisturemax

#initialize ADS, and encoder Object
ads1115 = ADS1115()
GPIO.setmode(GPIO.BCM)    #set Board Pin layout BCM for Broadcom layout
menucontrol = MenuControls()
encoder = RotaryEncoder()
encoder.StartThread()
