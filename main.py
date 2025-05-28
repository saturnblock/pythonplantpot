import json
import time
import RPi.GPIO as GPIO
import Control
#from Menu import Menu
import threading
import time
import math
from operator import truediv
import RPi.GPIO as GPIO
import adafruit_ads1x15.ads1115 as ADS  # Ensure the Adafruit CircuitPython ADS1x15 library is installed
import board
import busio
from adafruit_ads1x15.analog_in import AnalogIn

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

class ADS1115:  #ADC from Adafruit ADS1115 for analog sensor use with raspberryPi
    def __init__(self):
        # Create the I2C bus
        self.i2c = busio.I2C(board.SCL, board.SDA)
        # Create the ADC object using the I2C bus
        self.ads = ADS.ADS1115(self.i2c)

    def get_value (self, Channel):
        if Channel == "P0":                         #Moisturesensor is attached to Channel 0 on ADS1115 and is interfaced with P0
            readchan = AnalogIn(self.ads, ADS.P0)
            return readchan.value
        if Channel == "P1":                         #Tank level sensor is attached to Channel 1 on ADS1115 and is interfaced wit P1
            readchan = AnalogIn(self.ads, ADS.P1)
            return readchan.value
        elif Channel == "P2":                       #No Sensor is currently attached to Channel 2
            readchan = AnalogIn(self.ads, ADS.P2)
            return readchan.value
        if Channel == "P3":                         #No Sensor is currently attached to Channel 3
            readchan = AnalogIn(self.ads, ADS.P3)
            return readchan.value
        else:
            return "no valid channel"

    def moisture_sensor_status(self): #Returns the Moisture of the Soil in % as Integer
        value = self.get_value("P0")             #FMoisturesensor is attached to Channel 0
        moisturelevel = math.floor((value/26500)*100)
        return moisturelevel

    def tank_level(self):    #Returns the Level of the Water Tank in % as Integer
        value = self.get_value("P1")
        tanklevel = math.floor(((value/26500)*100))
        return tanklevel

    def tank_level_ml(self):  #Returns the remaining Tank Volume in Ml
        tanklevelml = (self.tank_level() / 100) * tankvolume
        return tanklevelml


class RotaryEncoder:    #Rotary Encoder from AzDelivery KY-040 to interface with the menu
    def __init__(self, clockPin = 5, dataPin = 6, switchPin = 13):
        GPIO.setwarnings(False) #no warnings, when pins are used for other programs
        GPIO.setmode(GPIO.BCM) #set Board Pin layout BCM for Broadcom layout
        #persistant values
        self.clockPin = clockPin    #clock Pin is attached to BCM Pin 5
        self.dataPin = dataPin      #data Pin is attached to BCM Pin 6
        self.switchPin = switchPin  #switch Pin is attached to BCM Pin 13
        self.lock = False           #set lock variable for rebouncetime whenever the encoder is turned to reduce faulty reading due to snapbacks


        #setup GPIO pins
        GPIO.setup(clockPin, GPIO.IN)
        GPIO.setup(dataPin, GPIO.IN)
        GPIO.setup(switchPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)    #Set High status on pin to look for falling signals

        #GPIO.setup(channel, GPIO.IN) set channel as an Input
        #GPIO.setup(channel, GPIO.OUT) set channel as an Output
        #chan_list = [11,12] ---> GPIO.setup(chan_list, GPIO.OUT) setup multiple channels at once

        #GPIO.setup(channel, GPIO.OUT, initial=GPIO.HIGH) initial setup for the state of a channel

        #GPIO.input(channel) read value of an input
        #GPIO.output(channel, state) set state of an output to 0 or 1 / True or False / GPIO.LOW or GPIO.HIGH
        #chan_list = [11,12] ---> GPIO.output(chan_list, GPIO.LOW) output to multiple channels at once
        #GPIO.cleanup() cleanup to reset all pins that the program has used
        #GPIO.add_event_detect(channel,GPIO.FALLING,callback=self._clockCallback,bouncetime=250) detect when pin falls .RISING for rising, then do this callback function, warte bevor man wieder auf eine änderung hört in ms

    def time_thread_encoder_func(self):    #Function for threaded timer to unlock the _clockCallback function delayed by a timer
        time.sleep(0.2)
        self.lock = False

    def start_thread(self):  #Function to start threads to look for falling signals on both clock and switch Pin to register a turn or press of the encoder
        GPIO.add_event_detect(self.clockPin, GPIO.FALLING, callback=self._clock_callback)
        GPIO.add_event_detect(self.switchPin, GPIO.FALLING, callback=self._switch_callback, bouncetime=5)

    def stop_thread(self):   #Function to stop threads
        GPIO.remove_event_detect(self.clockPin)
        GPIO.remove_event_detect(self.switchPin)

    def _clock_callback(self, pin):  #whenever a Falling of the Clock pin is detected this function is called to determine the direction
        if self.lock == False:
            self.lock = True
            if GPIO.input(self.clockPin) == 0:
                if GPIO.input(self.dataPin) == 1:   #if clock pin is 0 and data pin is 1 it was turned right
                    menucontrol.go_right()
                    timethreadencoder = threading.Thread(target=self.time_thread_encoder_func, daemon=True).start()
                else:                               #if clock and data pin are 0 it was turned left
                    menucontrol.go_left()
                    timethreadencoder = threading.Thread(target=self.time_thread_encoder_func, daemon=True).start()
            else:                                   #if clock pin is 1 a false reading happend
                print("else bei Clockcallback")
                timethreadencoder = threading.Thread(target=self.time_thread_encoder_func, daemon=True).start()

    def _switch_callback(self, pin): #whenever a falling of the switch pin is detected this function is called to register a press
        if GPIO.input(self.switchPin) == 0:
            menucontrol.confirm()


class MenuControls: #Class for Menu Controls to navigate the menu
    def __init__(self):
        pass

    def go_left(self):   #function is called when encoder was turned left
        print("left")

    def go_right(self):  #function is called when encoder was turned right
        print("right")

    def confirm(self):  #function is called when encoder was pressed
        print("confirm")


class Pump: #12V pipe Pump
    def __init__(self, pumpPin = 21):
        GPIO.setwarnings(False) #no warnings, when pins are used for other programs
        GPIO.setmode(GPIO.BCM) #set Board Pin layout BCM for Broadcom layout
        self.pumpPin = pumpPin

    def pump_timer(self):    #PumpTimer function called when Pump is started automatically with the StartPumpAutomatic function
        GPIO.output(self.pumpPin, 1)    #set Output of Pump Pin to High
        time.sleep(wateringamount*pumptimeoneml)    #Wait for the amount of time needed to pump the wanted amount of water from global wateringamount variable
        GPIO.output(self.pumpPin, 0)    #set Output of Pump Pin to Low

    def start_pump_automatic(self):   #Automatic Pump start to water the wateringamount from global variable
        if prewatercheck.water_tank() and prewatercheck.moisture_sensor() == True:    #Check the prewaterchecks before starting to pump
            threading.Thread(target=self.pump_timer(), daemon=True).start()  #start the PumpTimer function as a thread to not interrupt the programm
        else:
            print("automatic Watering cannot be started, because water tank is empty or soil is too moist") #Debug

    def start_pump_manual(self):  #Allows for manual start of the pump
        GPIO.output(self.pumpPin, 1)

    def stop_pump_manual(self):   #Allows for manual stopping of the pump
        GPIO.output(self.pumpPin, 0)


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
#menu = Menu()
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