import time
import board
import busio
import adafruit_ads1x15.ads1015 as ADS  # Ensure the Adafruit CircuitPython ADS1x15 library is installed
from adafruit_ads1x15.analog_in import AnalogIn

#if __name__ == "__main__":
 #   test = ADS1115()

  #  test.getValue("P1")

def getValue(param):
    pass


class ADS1115:
    def __init__(self):
        # Create the I2C bus
        self.i2c = busio.I2C(board.SCL, board.SDA)
        # Create the ADC object using the I2C bus
        self.ads = ADS.ADS1015(self.i2c)

    @staticmethod
    def getValue (self, Channel):
        if Channel == "P1":
            readchan = AnalogIn(self.ads, ADS.P1)
            return readchan.value
        elif Channel == "P2":
            readchan = AnalogIn(self.ads, ADS.P2)
            return readchan.value
        else: return "no valid channel"

        

    def Feuchtigkeitssensorstatus(self):
        Value = getValue("P1")
        return print(Value)



test = ADS1115()
while True:
    test.Feuchtigkeitssensorstatus()
    test.getValue("P3")
    time.sleep(0.5)



# Create single-ended input on channel 0
#chan = AnalogIn(ads, ADS.P1)

# Create differential input between channel 0 and 1
#chan = AnalogIn(ads, ADS.P0, ADS.P1)

#print("{:>5}\t{:>5}".format('raw', 'v'))

#while True:
    #print("{:>5}\t{:>5.3f}".format(chan.value, chan.voltage))
    #time.sleep(0.5)