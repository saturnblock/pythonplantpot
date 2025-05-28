import Interfaces
import main
import time
import threading
#from Interfaces import Pump
from main import wateringtimer, ads1115, wateringamount, moisturemax


class WateringControl:  #Main Control the watering of the plant
    def __init__(self):
        self._timer_thread = None
        self._stop_thread = False

    def run_timer_loop(self):   #Timer between watering processes
        timer = wateringtimer       #set timer according to global wateringtimer variable
        while timer >= 0 and not self._stop_thread:           #timer loop while the timer hs not run out and the thread hasn't been stopped
            time.sleep(1)
            timer -= 1
        if not self._stop_thread:    #check if the self.Stop function was used to stop the thread
            Pump.start_pump_automatic()   #Start automatic pump function with prechecks
            self.run_timer_loop()   #selfrestart the timer after watering
        else:
            print("The automatic watering program was stopped") #debug

    def start(self):    #start the automatic watering program using the sensors and set Variables to determine the right watering times
        if main.menu.confirm_start() and wateringtimer:
            self._stop_thread = False   #set a variable to shut down thread
            self._timer_thread = threading.Thread(target=self.run_timer_loop(), daemon=True)
            self._timer_thread.start() #start the timer loop as a thread

    def stop(self):    #stop the automatic watering programm
        self._stop_thread = True #set the stop variable of timer thread to True to catch at if statement



class PreWateringCheck: #Precheck class to check before automatic watering
    def __init__(self):
        pass

    def water_tank(self):    #precheck water tank level if enough water is remaining in tank
        if ads1115.tank_level_ml() >= wateringamount:
            return True

    def moisture_sensor(self):   #precheck if the soil is dry enough for another watering process
        if ads1115.moisture_sensor_status() >= moisturemax:
            return True


