import time
import RPi.GPIO as GPIO
import adafruit_ads1x15.ads1015 as ADS  # Ensure the Adafruit CircuitPython ADS1x15 library is installed
import board
import busio
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_blinka.microcontroller.allwinner.h618.pin import find_gpiochip_number

def getValue(param):
    pass


class ADS1115:
    def __init__(self):
        # Create the I2C bus
        self.i2c = busio.I2C(board.SCL, board.SDA)
        # Create the ADC object using the I2C bus
        self.ads = ADS.ADS1015(self.i2c)


    def getValue (self, Channel):
        if Channel == "P0":                         #Feuchtigkeitssensor ist an Channel 0 des ADS1115 angeschlossen
            readchan = AnalogIn(self.ads, ADS.P0)
            return readchan.value
        if Channel == "P1":
            readchan = AnalogIn(self.ads, ADS.P1)
            return readchan.value
        elif Channel == "P2":
            readchan = AnalogIn(self.ads, ADS.P2)
            return readchan.value
        if Channel == "P3":
            readchan = AnalogIn(self.ads, ADS.P3)
            return readchan.value
        else:
            return "no valid channel"


    def MoistureSensorStatus(self):
        value = self.getValue("P0")             #Feuchtigkeitssensor ist an Channel 0 des ADS1115 angeschlossen
        moisturelevel = (value/26100)*100       #TBD what is max value of ADC
        return moisturelevel

    def TankLevel(self):
        offsettanklevel = 2000                  #Offset für Ultraschall Abstand bei vollem Tank ist nicht 26100 sondern weniger
        value = self.getValue("P1")
        tanklevel = ((value-offsettanklevel)/(26100-offsettanklevel))*100    #TBD what is max value of ADC
        return tanklevel

class RotaryEncoder:
    def __init__(self, clockPin, dataPin, switchPin):
        GPIO.setwarnings(False) #no warnings, when pins are used for other programs
        #persist values
        self.clockPin = clockPin
        self.dataPin = dataPin
        self.switchPin = switchPin

        #setup pins
        GPIO.setup(clockPin, GPIO.IN)
        GPIO.setup(dataPin, GPIO.IN)
        GPIO.setup(switchPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        #GPIO.setup(channel, GPIO.IN) set channel as an Input
        #GPIO.setup(channel, GPIO.OUT) set channel as an Output
        #chan_list = [11,12] ---> GPIO.setup(chan_list, GPIO.OUT) setup multiple channels at once

        #GPIO.setup(channel, GPIO.OUT, initial=GPIO.HIGH) initial setup for the state of a channel

        #GPIO.input(channel) read value of an input
        #GPIO.output(channel, state) set state of an output to 0 or 1 / True or False / GPIO.LOW or GPIO.HIGH
        #chan_list = [11,12] ---> GPIO.output(chan_list, GPIO.LOW) output to multiple channels at once
        #GPIO.cleanup() cleanup to reset all pins that the program has used
        #GPIO.add_event_detect(channel,GPIO.FALLING,callback=self._clockCallback,bouncetime=250) detect when pin falls .RISING for rising, then do this callback function, warte bevor man wieder auf eine änderung hört in ms

    def StartThread(self):
        GPIO.add_event_detect(self.clockPin, GPIO.FALLING, callback=self._clockCallback, bouncetime=250)
        GPIO.add_event_detect(self.switchPin, GPIO.FALLING, callback=self._switchCallback, bouncetime=300)

    def StopThread(self):
        GPIO.remove_event_detect(self.clockPin)
        GPIO.remove_event_detect(self.switchPin)

    def _clockCallback(self, pin):  #whenever a Falling of the Clock pin happened
        if GPIO.input(self.clockPin) == 0:
            data = GPIO.input(self.dataPin)
            if data == 1:
                menucontrol.GoLeft()
            else:
                menucontrol.GoRight()

    def _switchCallback(self, pin):
        if GPIO.input(self.switchPin) == 0:
            menucontrol.Confirm()

class MenuControls:
    def __init__(self):
        pass


    def GoLeft(self):
        print("left")


    def GoRight(self):
        print("right")


    def Confirm(self):
        print("confirm")



if __name__ == "__main__":
    test = ADS1115()
    GPIO.setmode(GPIO.BOARD)    #set Board Pin layout BCM for Broadcom layout
    menucontrol = MenuControls()
    encoder = RotaryEncoder(5,6,13)
    encoder.StartThread()

    test.MoistureSensorStatus()

    test.getValue("P3")

    try:
        while True:
            test.MoistureSensorStatus()
            time.sleep(0.1)

    finally:
        GPIO.cleanup()
        encoder.stopThread()