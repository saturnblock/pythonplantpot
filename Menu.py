import json
from main import defaultmoisturemax, wateringtimer, wateringamount, moisturesensoruse


class Menu: #Menu class for Menu configuration

    def __init__(self):
        pass

    def watering_sensor_dont_use(self):    #Function to disable Watering sensor. Writes the change in the config file to save
        moisturemax = 100   #set moisturemax to goaround the precheck
        moisturesensoruse = 0   #set the moisturesensorstatus to 0 not used and write it to the config.json file
        try:
            with open('config.json', 'w') as f:
                self.data = [{"timer":wateringtimer, "moisturemax":moisturemax, "wateringamount":wateringamount, "moisturesensoruse":moisturesensoruse}]
                json.dump(self.data, f, indent=4)
        except:
            print("error in setting the moisture sensor use to 0 in config.json")

    def watering_sensor_use(self, moisturemax):    #Function to enable Watering sensor. Writes the change in the config file to save
        self.moisturemax = moisturemax  #set moisturemax to global Variable moisturemax
        moisturesensoruse = 1   #set the moisturesensorstatus to 1 used and write it to the config.json file
        try:
            with open('config.json', 'w') as f:
                self.data = [{"timer":wateringtimer, "moisturemax":moisturemax, "wateringamount":wateringamount, "moisturesensoruse":moisturesensoruse}]
                json.dump(self.data, f, indent=4)
        except:
            print("error in setting the moisture sensor use to 1 in config.json")

    def confirm_start(self):   #user needs to confirm the start of the automatic program
        #setup that the user needs to confirm the start of the programm
        if user.input.confirmed == 1
            self.confirmation_start = True
            return self.confirmation_start