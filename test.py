import json
import time
import RPi.GPIO as GPIO
#import Control
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


try:
    pump = Pump()
    while True:
        print("Switch On / High 3.3V")
        pump.start_pump_manual()
        time.sleep(2)
        print("Switch Off / Low 0V. To end test press enter")
        pump.stop_pump_manual()
finally:
    GPIO.cleanup()
