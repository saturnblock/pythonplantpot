import Interfaces
import main
import time
import threading
from Interfaces import Pump
from main import wateringtimer, ads1115, wateringamount, moisturemax


class WateringControl:
    def __init__(self):
        pass

    def WateringTimer(self):
        timer = wateringtimer
        while timer >= 0:
            time.sleep(1)
            timer -= 1
        Pump.StartPumpAutomatic()

class PreWateringCheck:
    def __init__(self):
        pass

    def WaterTank(self):
        if ads1115.TankLevelMl() >= wateringamount:
            return True

    def MoistureSensor(self):
        if ads1115.MoistureSensorStatus() >= moisturemax:
            return True


