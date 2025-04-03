import threading
import time
import math
from operator import truediv
import RPi.GPIO as GPIO
import adafruit_ads1x15.ads1115 as ADS  # Ensure the Adafruit CircuitPython ADS1x15 library is installed
import board
import busio
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_blinka.microcontroller.allwinner.h618.pin import find_gpiochip_number
from main import menucontrol, wateringamount, pumptimeoneml, tankvolume, prewatercheck


class ADS1115:  #ADC from Adafruit ADS1115 for analog sensor use with raspberryPi
    def __init__(self):
        # Create the I2C bus
        self.i2c = busio.I2C(board.SCL, board.SDA)
        # Create the ADC object using the I2C bus
        self.ads = ADS.ADS1115(self.i2c)

    def getValue (self, Channel):
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

    def MoistureSensorStatus(self): #Returns the Moisture of the Soil in % as Integer
        value = self.getValue("P0")             #FMoisturesensor is attached to Channel 0
        moisturelevel = math.floor((value/26500)*100)
        return moisturelevel

    def TankLevel(self):    #Returns the Level of the Water Tank in % as Integer
        value = self.getValue("P1")
        tanklevel = math.floor(((value/26500)*100))
        return tanklevel

    def TankLevelMl(self):  #Returns the remaining Tank Volume in Ml
        tanklevelml = (self.TankLevel()/100)*tankvolume
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

    def timethreadencoderfunc(self):    #Function for threaded timer to unlock the _clockCallback function delayed by a timer
        time.sleep(0.2)
        self.lock = False

    def StartThread(self):  #Function to start threads to look for falling signals on both clock and switch Pin to register a turn or press of the encoder
        GPIO.add_event_detect(self.clockPin, GPIO.FALLING, callback=self._clockCallback)
        GPIO.add_event_detect(self.switchPin, GPIO.FALLING, callback=self._switchCallback, bouncetime=5)

    def StopThread(self):   #Function to stop threads
        GPIO.remove_event_detect(self.clockPin)
        GPIO.remove_event_detect(self.switchPin)

    def _clockCallback(self, pin):  #whenever a Falling of the Clock pin is detected this function is called to determine the direction
        if self.lock == False:
            self.lock = True
            if GPIO.input(self.clockPin) == 0:
                if GPIO.input(self.dataPin) == 1:   #if clock pin is 0 and data pin is 1 it was turned right
                    menucontrol.GoRight()
                    threading.Thread(target=self.timethreadencoderfunc, daemon=True).start()
                else:                               #if clock and data pin are 0 it was turned left
                    menucontrol.GoLeft()
                    threading.Thread(target=self.timethreadencoderfunc, daemon=True).start()
            else:                                   #if clock pin is 1 a false reading happend
                print("else bei Clockcallback")
                threading.Thread(target=self.timethreadencoderfunc, daemon=True).start()

    def _switchCallback(self, pin): #whenever a falling of the switch pin is detected this function is called to register a press
        if GPIO.input(self.switchPin) == 0:
            menucontrol.Confirm()


class MenuControls: #Class for Menu Controls to navigate the menu
    def __init__(self):
        pass

    def GoLeft(self):   #function is called when encoder was turned left
        print("left")

    def GoRight(self):  #function is called when encoder was turned right
        print("right")

    def Confirm(self):  #function is called when encoder was pressed
        print("confirm")


class Pump: #12V pipe Pump
    def __init__(self, pumpPin = 21):
        GPIO.setwarnings(False) #no warnings, when pins are used for other programs
        GPIO.setmode(GPIO.BCM) #set Board Pin layout BCM for Broadcom layout
        self.pumpPin = pumpPin

    def PumpTimer(self):    #PumpTimer function called when Pump is started automatically with the StartPumpAutomatic function
        GPIO.output(self.pumpPin, 1)    #set Output of Pump Pin to High
        time.sleep(wateringamount*pumptimeoneml)    #Wait for the amount of time needed to pump the wanted amount of water from global wateringamount variable
        GPIO.output(self.pumpPin, 0)    #set Output of Pump Pin to Low

    def StartPumpAutomatic(self):   #Automatic Pump start to water the wateringamount from global variable
        if prewatercheck.WaterTank() and prewatercheck.MoistureSensor() == True:    #Check the prewaterchecks before starting to pump
            threading.Thread(target=self.PumpTimer(), daemon=True).start()  #start the PumpTimer function as a thread to not interrupt the programm
        else:
            print("automatic Watering cannot be started, because water tank is empty or soil is too moist") #Debug

    def StartPumpManual(self):  #Allows for manual start of the pump
        GPIO.output(self.pumpPin, 1)

    def StopPumpManual(self):   #Allows for manual stopping of the pump
        GPIO.output(self.pumpPin, 0)



# if __name__ == "__main__":
#
#     try:
#         test = ADS1115()
#         GPIO.setmode(GPIO.BCM)    #set Board Pin layout BCM for Broadcom layout
#
#         GPIO.setup(21, GPIO.OUT)
#         GPIO.output(21, 1)
#         while True:
#             print("low")
#             GPIO.output(21, 0)
#             time.sleep(5)
#             print("low")
#             GPIO.output(21, 1)
#             time.sleep(5)
#         # menucontrol = MenuControls()
#         # encoder = RotaryEncoder(5,6,13)
#         # encoder.StartThread()
#
#         # test.MoistureSensorStatus()
#         #
#         # test.getValue("P3")
#         # while True:
#         #     moisturelevel = test.MoistureSensorStatus()
#         #     print(moisturelevel)
#         #     #print(GPIO.input(13),"switch")
#         #     #print(GPIO.input(5),"clock")
#         #     #print(GPIO.input(6),"data")
#         #     #print("\n")
#         #     time.sleep(0.1)
#     #try:
#         #while True:
#             #test.MoistureSensorStatus()
#             #time.sleep(0.1)
#
#     finally:
#         GPIO.cleanup()
#         encoder.StopThread()