import Interfaces
import main
import time
import threading
from Interfaces import Pump
from main import wateringtimer, ads1115, wateringamount, moisturemax


class WateringControl:  #Main Control the watering of the plant
    def __init__(self):
        pass

    def StartWateringTimer(self):   #Timer between watering processes
        timer = wateringtimer       #set timer according to global wateringtimer variable
        while timer >= 0:           #timer loop
            time.sleep(1)
            timer -= 1
        Pump.StartPumpAutomatic()   #Start automatic pump function with prechecks
        self.StartWateringTimer()   #selfrestart the timer after watering


class PreWateringCheck: #Precheck class to check before automatic watering
    def __init__(self):
        pass

    def WaterTank(self):    #precheck water tank level if enough water is remaining in tank
        if ads1115.TankLevelMl() >= wateringamount:
            return True

    def MoistureSensor(self):   #precheck if the soil is dry enough for another watering process
        if ads1115.MoistureSensorStatus() >= moisturemax:
            return True


