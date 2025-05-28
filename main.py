import json
import time
import RPi.GPIO as GPIO
import Control
from Interfaces import ADS1115, MenuControls, Pump#, RotaryEncoder
from Menu import Menu

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
def json_file_default():      #if json file was missing this function is used for debugging and notifications
    print("config file was empty or missing, default values were added")
try:                                        #opening json file conifg.json to read all content and write it to data for later extraction
    with open('config.json', 'r') as f:
        data = json.load(f)
        print("config file successfully opened and read")
except:
    with open('config.json', 'w+') as f:    #if json file is empty or missing a new file is created and default values are added
        data = [{"timer":defaultwateringtimer, "moisturemax":defaultmoisturemax, "wateringamount":defaultwateringamount, "moisturesensoruse":defaultmoisturesensoruse}]
        json.dump(data, f, indent=4)
        json_file_default()
wateringtimer = data[0]['timer']                    #Global Variable for Timer
wateringamount = data[0]['wateringamount']          #Global Variable for wateringamount
moisturemax = data[0]['moisturemax']                #Global Variable for moisturemax
moisturesensoruse = data[0]['moisturesensoruse']    #Global Variable fo moisturesensoruse

#initialize ADS, encoder, PreWateringCheck and WateringControl Object and Start Thread for the encoder to interupt when Encoder is used
ads1115 = ADS1115()
menucontrol = MenuControls()
menu = Menu()
#encoder = RotaryEncoder()
#encoder.start_thread()
pump = Pump
prewatercheck = Control.PreWateringCheck()
wateringcontrol = Control.WateringControl()





#main part of file
try:
    print("This is the Value of Channel 0 of the adc ADS1115 (normally Moisture Sensor) in %:\n")
    ads1115.moisture_sensor_status()
    time.sleep(1)
    print("This is the value of Channel 1 of the adc ADS1115 (normally Water Tank Sensor) in ml:\n")
    ads1115.tank_level_ml()
    time.sleep(1)
    print("Test now the function of the Encoder by twisting and pushing and end test with enter")
    input()
    print("Now test the Pump switch output it will oscillate between high and low. End Test with enter")
    time.sleep(1)
    while not input():
        print("Switch On / High 3.3V")
        pump.start_pump_manual()
        time.sleep(2)
        print("Switch Off / Low 0V. To end test press enter")
        pump.stop_pump_manual()
    #print("now test the automatic watering control function")
    time.sleep(1)
    #wateringcontrol.start()
    #time.sleep(10)
    #wateringcontrol.stop()



finally:
    GPIO.cleanup()
    encoder.stop_thread()