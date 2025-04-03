import json
from Adafruit_GPIO import GPIO
import Control
from Interfaces import RotaryEncoder, ADS1115, MenuControls

#set default values for plant pot for the event of missing or corrupted config.json file
defaultwateringtimer = 100 #in s
defaultwateringamount = 50 #in ml
defaultmoisturemax = 30 #in %
defaultmoisturesensoruse = 1 #1 or 0 if used or not
pumptimeoneml = 0.4 #in sec time to pump one ml
tankvolume = 500 #Tankvolume in ml when measured with 100%

#initialize Global Variables
wateringtimer = defaultwateringtimer
wateringamount = defaultwateringamount
moisturemax = defaultmoisturemax
moisturesensoruse = defaultmoisturesensoruse

#jasonfile config read or write of default values if json file is corrupted or missing --> writing of config data into global variables
def jsonfiledefault():      #if json file was missing this function is used for debugging and notifications
    print("config file was empty or missing, default values were added")
try:                                        #opening json file conifg.json to read all content and write it to data for later extraction
    with open('config.json', 'r') as f:
        data = json.load(f)
        print("config file successfully opened and read")
except:
    with open('config.json', 'w+') as f:    #if json file is empty or missing a new file is created and default values are added
        data = [{"timer":defaultwateringtimer, "moisturemax":defaultmoisturemax, "wateringamount":defaultwateringamount, "moisturesensoruse":defaultmoisturesensoruse}]
        json.dump(data, f, indent=4)
        jsonfiledefault()
wateringtimer = data[0]['timer']                    #Global Variable for Timer
wateringamount = data[0]['wateringamount']          #Global Variable for wateringamount
moisturemax = data[0]['moisturemax']                #Global Variable for moisturemax
moisturesensoruse = data[0]['moisturesensoruse']    #Global Variable fo moisturesensoruse

#initialize ADS, encoder, PreWateringCheck and WateringControl Object and Start Thread for the encoder to interupt when Encoder is used
ads1115 = ADS1115()
menucontrol = MenuControls()
encoder = RotaryEncoder()
encoder.StartThread()
prewatercheck = Control.PreWateringCheck()
wateringcontrol = Control.WateringControl()



#main part of file
try:
    pass
finally:
    GPIO.cleanup()
    encoder.StopThread()