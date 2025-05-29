import json
import time
import RPi.GPIO as GPIO
import threading
import math
from operator import truediv # Not used in the provided code, but kept for completeness
import adafruit_ads1x15.ads1115 as ADS  # Ensure the Adafruit CircuitPython ADS1x15 library is installed
import board
import busio
from adafruit_ads1x15.analog_in import AnalogIn

# Set default values for plant pot for the event of missing or corrupted config.json file
defaultwateringtimer = 100  # in s
defaultwateringamount = 50  # in ml
defaultmoisturemax = 30     # in %
defaultmoisturesensoruse = 1 # 1 or 0 if used or not
pumptimeoneml = 0.4         # in sec time to pump one ml
tankvolume = 500            # Tankvolume in ml when measured with 100%

# Initialize Global Variables
wateringtimer = defaultwateringtimer
wateringamount = defaultwateringamount
moisturemax = defaultmoisturemax
moisturesensoruse = defaultmoisturesensoruse

class ADS1115:  # ADC from Adafruit ADS1115 for analog sensor use with raspberryPi
    def __init__(self):
        # Create the I2C bus
        self.i2c = busio.I2C(board.SCL, board.SDA)
        # Create the ADC object using the I2C bus
        self.ads = ADS.ADS1115(self.i2c)
        # ADS1115 has a default gain of 1, which means it reads up to 4.096V.
        # Max value for ADS1115 with default gain is 26400-26600 (approx)
        # We'll use 26500 as the reference for 100%

    def get_value(self, Channel):
        """
        Reads the analog value from the specified ADC channel.
        Channels are referred to as P0, P1, P2, P3.
        """
        if Channel == "P0":
            readchan = AnalogIn(self.ads, ADS.P0)
            return readchan.value
        elif Channel == "P1":
            readchan = AnalogIn(self.ads, ADS.P1)
            return readchan.value
        elif Channel == "P2":
            readchan = AnalogIn(self.ads, ADS.P2)
            return readchan.value
        elif Channel == "P3":
            readchan = AnalogIn(self.ads, ADS.P3)
            return readchan.value
        else:
            print(f"Error: No valid channel '{Channel}' specified for ADS1115.")
            return -1 # Return an error value

    def moisture_sensor_status(self): # Returns the Moisture of the Soil in % as Integer
        """
        Reads the moisture sensor value from P0 and converts it to a percentage.
        Assumes 26500 is the max dry value (0% moisture) and 0 is fully wet (100% moisture).
        Adjust the mapping (26500) based on your sensor's actual dry reading.
        """
        value = self.get_value("P0")
        if value == -1: # Handle error from get_value
            return 0 # Or some other default/error value

        # Invert the reading: higher sensor value means drier soil.
        # Max dry value (e.g., 26500) should map to 0% moisture.
        # Min wet value (e.g., 0) should map to 100% moisture.
        # A simple linear mapping: moisture = 100 - (value / max_dry_value * 100)
        # Or, if 26500 is 0% and 0 is 100%: moisture = (max_dry_value - value) / max_dry_value * 100
        # Let's assume 26500 is dry (0%) and 0 is wet (100%).
        # A common sensor mapping is that lower ADC values mean more moisture.
        # If your sensor reads higher values when DRY and lower when WET:
        # For example, if 26500 is completely dry (0% moisture) and 10000 is fully wet (100% moisture)
        # moisturelevel = 100 - ((value - 10000) / (26500 - 10000)) * 100
        # For simplicity, let's assume 0 is 0% and 26500 is 100% for now, as per original code's logic.
        # If your sensor reads higher when dry, you might need to invert this logic.
        moisturelevel = math.floor((value / 26500) * 100)
        # Ensure moisturelevel is between 0 and 100
        moisturelevel = max(0, min(100, moisturelevel))
        return moisturelevel

    def tank_level(self):    # Returns the Level of the Water Tank in % as Integer
        """
        Reads the tank level sensor value from P1 and converts it to a percentage.
        Assumes 26500 is the max full value (100% tank) and 0 is empty (0% tank).
        Adjust the mapping (26500) based on your sensor's actual full reading.
        """
        value = self.get_value("P1")
        if value == -1: # Handle error from get_value
            return 0 # Or some other default/error value
        tanklevel = math.floor(((value / 26500) * 100))
        # Ensure tanklevel is between 0 and 100
        tanklevel = max(0, min(100, tanklevel))
        return tanklevel

    def tank_level_ml(self):  # Returns the remaining Tank Volume in Ml
        """
        Calculates the remaining tank volume in milliliters based on the percentage level.
        """
        tanklevelml = (self.tank_level() / 100) * tankvolume
        return tanklevelml


class RotaryEncoder:    # Rotary Encoder from AzDelivery KY-040 to interface with the menu
    def __init__(self, clockPin = 5, dataPin = 6, switchPin = 13):
        GPIO.setwarnings(False) # no warnings, when pins are used for other programs
        GPIO.setmode(GPIO.BCM) # set Board Pin layout BCM for Broadcom layout
        # persistent values
        self.clockPin = clockPin    # clock Pin is attached to BCM Pin 5
        self.dataPin = dataPin      # data Pin is attached to BCM Pin 6
        self.switchPin = switchPin  # switch Pin is attached to BCM Pin 13
        self.lock = False           # set lock variable for rebounce time whenever the encoder is turned to reduce faulty reading due to snapbacks

        # setup GPIO pins
        GPIO.setup(clockPin, GPIO.IN, pull_up_down=GPIO.PUD_UP) # Clock pin usually needs pull-up
        GPIO.setup(dataPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Data pin usually needs pull-up
        GPIO.setup(switchPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)    # Set High status on pin to look for falling signals

    def time_thread_encoder_func(self):    # Function for threaded timer to unlock the _clockCallback function delayed by a timer
        """
        A small delay to debounce the rotary encoder turns.
        """
        time.sleep(0.2)
        self.lock = False

    def start_thread(self):  # Function to start threads to look for falling signals on both clock and switch Pin to register a turn or press of the encoder
        """
        Attaches event detection to the rotary encoder pins.
        """
        GPIO.add_event_detect(self.clockPin, GPIO.FALLING, callback=self._clock_callback, bouncetime=50) # Added bouncetime
        GPIO.add_event_detect(self.switchPin, GPIO.FALLING, callback=self._switch_callback, bouncetime=300) # Added bouncetime for switch

    def stop_thread(self):   # Function to stop threads
        """
        Removes event detection from the rotary encoder pins.
        """
        GPIO.remove_event_detect(self.clockPin)
        GPIO.remove_event_detect(self.switchPin)

    def _clock_callback(self, pin):  # whenever a Falling of the Clock pin is detected this function is called to determine the direction
        """
        Callback function for the clock pin falling edge.
        Determines the direction of rotation (left or right).
        """
        if not self.lock: # Check if not locked (debouncing)
            self.lock = True # Lock to prevent multiple rapid triggers
            # Read data pin after clock pin has fallen
            # This is a common way to detect direction for KY-040
            if GPIO.input(self.dataPin) == 1:   # if clock pin is 0 and data pin is 1 it was turned right
                menucontrol.go_right()
            else:                               # if clock and data pin are 0 it was turned left
                menucontrol.go_left()
            # Start a new thread to unlock after a delay for debouncing
            threading.Thread(target=self.time_thread_encoder_func, daemon=True).start()
        # else:
        #     print("Clock callback ignored due to lock") # Debugging for debouncing

    def _switch_callback(self, pin): # whenever a falling of the switch pin is detected this function is called to register a press
        """
        Callback function for the switch pin falling edge.
        Registers a button press.
        """
        # The bouncetime in add_event_detect should handle most debouncing.
        # A small delay here can further prevent multiple triggers if needed,
        # but usually, the bouncetime parameter is sufficient.
        if GPIO.input(self.switchPin) == 0: # Confirm button is still pressed (debounced)
            menucontrol.confirm()


class MenuControls: # Class for Menu Controls to navigate the menu
    def __init__(self):
        pass

    def go_left(self):   # function is called when encoder was turned left
        print("Encoder turned left")
        # Add your menu navigation logic here (e.g., decrement selected item)

    def go_right(self):  # function is called when encoder was turned right
        print("Encoder turned right")
        # Add your menu navigation logic here (e.g., increment selected item)

    def confirm(self):  # function is called when encoder was pressed
        print("Encoder button pressed (Confirm)")
        # Add your menu confirmation logic here (e.g., select item, enter submenu)


class Pump: # 12V pipe Pump
    def __init__(self, pumpPin = 21):
        GPIO.setwarnings(False) # no warnings, when pins are used for other programs
        GPIO.setmode(GPIO.BCM) # set Board Pin layout BCM for Broadcom layout
        self.pumpPin = pumpPin
        GPIO.setup(self.pumpPin, GPIO.OUT, initial=GPIO.LOW) # Setup pump pin as output, initially off

    def pump_timer(self):    # PumpTimer function called when Pump is started automatically with the StartPumpAutomatic function
        """
        Controls the pump for a duration based on the global watering amount.
        """
        print(f"Starting pump for {wateringamount * pumptimeoneml} seconds to deliver {wateringamount} ml.")
        GPIO.output(self.pumpPin, GPIO.HIGH)    # set Output of Pump Pin to High (turn pump on)
        time.sleep(wateringamount * pumptimeoneml)    # Wait for the amount of time needed to pump the wanted amount of water
        GPIO.output(self.pumpPin, GPIO.LOW)    # set Output of Pump Pin to Low (turn pump off)
        print("Pump stopped.")

    def start_pump_automatic(self):   # Automatic Pump start to water the wateringamount from global variable
        """
        Initiates automatic watering if pre-checks pass.
        """
        # Use the global prewatercheck instance
        if prewatercheck.water_tank() and prewatercheck.moisture_sensor():    # Check the prewaterchecks before starting to pump
            print("Pre-checks passed. Starting automatic pump operation.")
            # Start the pump_timer function as a thread to not interrupt the program
            threading.Thread(target=self.pump_timer, daemon=True).start()
        else:
            print("Automatic watering cannot be started, because water tank is empty or soil is too moist.") # Debug

    def start_pump_manual(self):  # Allows for manual start of the pump
        """
        Manually turns the pump on.
        """
        print("Manual pump start.")
        GPIO.output(self.pumpPin, GPIO.HIGH)

    def stop_pump_manual(self):   # Allows for manual stopping of the pump
        """
        Manually turns the pump off.
        """
        print("Manual pump stop.")
        GPIO.output(self.pumpPin, GPIO.LOW)


class PreWateringCheck: # Precheck class to check before automatic watering
    def __init__(self, ads_instance):
        self.ads1115 = ads_instance

    def water_tank(self):    # precheck water tank level if enough water is remaining in tank
        """
        Checks if there is enough water in the tank for the watering amount.
        """
        current_tank_ml = self.ads1115.tank_level_ml()
        if current_tank_ml >= wateringamount:
            print(f"Tank level OK: {current_tank_ml:.2f} ml available, need {wateringamount} ml.")
            return True
        else:
            print(f"Tank level LOW: {current_tank_ml:.2f} ml available, need {wateringamount} ml.")
            return False

    def moisture_sensor(self):   # precheck if the soil is dry enough for another watering process
        """
        Checks if the soil moisture is below the maximum allowed level.
        """
        current_moisture = self.ads1115.moisture_sensor_status()
        if moisturesensoruse == 0: # If moisture sensor is not used, always return True
            print("Moisture sensor use is disabled. Assuming soil is dry enough.")
            return True
        elif current_moisture >= moisturemax: # Assuming 'moisturemax' is the threshold for 'dry enough'
            print(f"Soil moisture OK: {current_moisture}% (max allowed: {moisturemax}%).")
            return True
        else:
            print(f"Soil too moist: {current_moisture}% (max allowed: {moisturemax}%).")
            return False


class WateringControl:  # Main Control the watering of the plant
    def __init__(self, pump_instance, precheck_instance):
        self._timer_thread = None
        self._stop_thread = False
        self.pump = pump_instance
        self.prewatercheck = precheck_instance

    def run_timer_loop(self):   # Timer between watering processes
        """
        The main loop for automatic watering, runs on a timer.
        """
        timer = wateringtimer       # set timer according to global wateringtimer variable
        print(f"Automatic watering timer started for {timer} seconds.")
        while timer >= 0 and not self._stop_thread:           # timer loop while the timer has not run out and the thread hasn't been stopped
            time.sleep(1)
            timer -= 1
            # print(f"Timer: {timer}s remaining") # Uncomment for detailed timer debug

        if not self._stop_thread:    # check if the self.Stop function was used to stop the thread
            print("Timer finished. Attempting automatic watering.")
            self.pump.start_pump_automatic()   # Start automatic pump function with prechecks
            self.run_timer_loop()   # self-restart the timer after watering
        else:
            print("The automatic watering program was stopped.") # debug

    def start(self):    # start the automatic watering program using the sensors and set Variables to determine the right watering times
        """
        Starts the automatic watering program.
        """
        # Removed main.menu.confirm_start() as Menu class is commented out and main is not defined.
        # Assuming direct start for now.
        if wateringtimer > 0: # Only start if a valid watering timer is set
            self._stop_thread = False   # set a variable to shut down thread
            print("Starting automatic watering program...")
            # Target should be the function itself, not the result of calling it.
            self._timer_thread = threading.Thread(target=self.run_timer_loop, daemon=True)
            self._timer_thread.start() # start the timer loop as a thread
        else:
            print("Watering timer is not set. Automatic watering cannot start.")


    def stop(self):    # stop the automatic watering programm
        """
        Stops the automatic watering program.
        """
        if self._timer_thread and self._timer_thread.is_alive():
            print("Stopping automatic watering program...")
            self._stop_thread = True # set the stop variable of timer thread to True to catch at if statement
            # It might take up to 1 second for the thread to recognize the stop signal
            # You could add a join() here if you need to wait for the thread to truly finish,
            # but for a daemon thread, it's usually not necessary for a clean shutdown.
        else:
            print("Automatic watering program is not running.")


# JSON file config read or write of default values if json file is corrupted or missing --> writing of config data into global variables
def json_file_default():      # if json file was missing this function is used for debugging and notifications
    print("Config file was empty or missing, default values were added.")

try:                                        # opening json file conifg.json to read all content and write it to data for later extraction
    with open('config.json', 'r') as f:
        data = json.load(f)
        print("Config file successfully opened and read.")
except FileNotFoundError: # Catch specific error for missing file
    print("config.json not found. Creating with default values.")
    data = [{"timer":defaultwateringtimer, "moisturemax":defaultmoisturemax, "wateringamount":defaultwateringamount, "moisturesensoruse":defaultmoisturesensoruse}]
    with open('config.json', 'w') as f:    # if json file is empty or missing a new file is created and default values are added
        json.dump(data, f, indent=4)
    json_file_default()
except json.JSONDecodeError: # Catch specific error for corrupted JSON
    print("config.json is corrupted. Overwriting with default values.")
    data = [{"timer":defaultwateringtimer, "moisturemax":defaultmoisturemax, "wateringamount":defaultwateringamount, "moisturesensoruse":defaultmoisturesensoruse}]
    with open('config.json', 'w') as f:
        json.dump(data, f, indent=4)
    json_file_default()
except Exception as e: # Catch any other unexpected errors during file handling
    print(f"An unexpected error occurred while handling config.json: {e}")
    data = [{"timer":defaultwateringtimer, "moisturemax":defaultmoisturemax, "wateringamount":defaultwateringamount, "moisturesensoruse":defaultmoisturesensoruse}]
    with open('config.json', 'w') as f:
        json.dump(data, f, indent=4)
    json_file_default()

wateringtimer = data[0]['timer']                    # Global Variable for Timer
wateringamount = data[0]['wateringamount']          # Global Variable for wateringamount
moisturemax = data[0]['moisturemax']                # Global Variable for moisturemax
moisturesensoruse = data[0]['moisturesensoruse']    # Global Variable for moisturesensoruse

# Initialize ADS, encoder, PreWateringCheck and WateringControl Object
# and Start Thread for the encoder to interrupt when Encoder is used
ads1115 = ADS1115()
menucontrol = MenuControls() # Used by RotaryEncoder callbacks
encoder = RotaryEncoder() # Instantiate the encoder
pump = Pump() # Instantiate the pump object
prewatercheck = PreWateringCheck(ads1115) # Pass ads1115 instance to prewatercheck
wateringcontrol = WateringControl(pump, prewatercheck) # Pass pump and prewatercheck instances to wateringcontrol

# main part of file
try:
    print("\n--- Starting System Tests ---")

    # Start encoder thread early if you want to use it during tests
    encoder.start_thread()
    print("Rotary Encoder thread started. Twist and press the encoder.")
    sensor_test_running = True
    while sensor_test_running:
        print("\n--- ADS1115 Sensor Readings ---")
        print(f"Value of Channel 0 (Moisture Sensor): {ads1115.get_value('P0')} (Raw ADC)")
        print(f"Moisture Sensor Status: {ads1115.moisture_sensor_status()}%")
        time.sleep(1)
        print(f"Value of Channel 1 (Water Tank Sensor): {ads1115.get_value('P1')} (Raw ADC)")
        print(f"Water Tank Level: {ads1115.tank_level()}%")
        print(f"Water Tank Level in ml: {ads1115.tank_level_ml():.2f}ml")
        time.sleep(1)
        try:
            # Use a short timeout for input to make it somewhat non-blocking for the loop
            # This requires sys and select, which might be overkill for this simple test.
            # Sticking to original input() for simplicity, user will have to press Enter to stop.
            user_input = input("Type stop to stop sensor test, or press Enter to continue to next cycle: ")
            if user_input == "stop": # If user just pressed Enter (empty string)
                sensor_test_running = False
            # If user types something, test_running remains True and loop continues
        except KeyboardInterrupt:
            sensor_test_running = False # Allow Ctrl+C to stop
        except EOFError: # For environments where input() might get EOF
            sensor_test_running = False

    print("\n--- Rotary Encoder Test ---")
    print("Test the function of the Encoder by twisting and pushing. Press Enter to end this test.")
    input("Press Enter to continue after testing encoder...") # Blocking input to allow user to test encoder
    print("Encoder test finished.")

    print("\n--- Pump Manual Test ---")
    print("Now test the Pump switch output. It will oscillate between high and low. Press Enter to end this test.")
    input("Press Enter to start pump test...")

    # Loop for manual pump test, will run until user presses Enter again
    pump_test_running = True
    while pump_test_running:
        print("Switch On / High 3.3V")
        pump.start_pump_manual()
        time.sleep(5)
        print("Switch Off / Low 0V. To end test press Enter again.")
        pump.stop_pump_manual()
        # Check if Enter was pressed. This is a bit tricky with blocking input.
        # For a non-blocking check, you'd need a more complex input handling.
        # For now, the user has to press Enter *after* the cycle to stop.
        try:
            # Use a short timeout for input to make it somewhat non-blocking for the loop
            # This requires sys and select, which might be overkill for this simple test.
            # Sticking to original input() for simplicity, user will have to press Enter to stop.
            user_input = input("Press Enter to stop pump test, or type anything and press Enter to continue to next cycle: ")
            if user_input == "": # If user just pressed Enter (empty string)
                pump_test_running = False
            # If user types something, test_running remains True and loop continues
        except KeyboardInterrupt:
            pump_test_running = False # Allow Ctrl+C to stop
        except EOFError: # For environments where input() might get EOF
            pump_test_running = False


    print("Pump manual test finished.")

    #print("\n--- Automatic Watering Control Test ---")
    #print(f"Attempting to start automatic watering with timer: {wateringtimer}s, amount: {wateringamount}ml, moisture max: {moisturemax}%, sensor use: {moisturesensoruse}")
    #wateringcontrol.start()
    #print("Automatic watering started. It will run in the background.")
    #print("Waiting for 10 seconds to observe... (or until timer runs out if shorter)")
    #time.sleep(min(10, wateringtimer + 5)) # Wait for a bit, or until timer finishes + buffer

    #print("Attempting to stop automatic watering.")
    #wateringcontrol.stop()
    #time.sleep(5) # Give a moment for the stop to register

    #print("\n--- All tests completed ---")

except Exception as e:
    print(f"\nAn error occurred during execution: {e}")
    import traceback
    traceback.print_exc() # Print full traceback for debugging

finally:
    print("\n--- Cleaning up GPIO pins and stopping threads ---")
    if 'encoder' in locals() and encoder: # Check if encoder was initialized
        encoder.stop_thread()
    GPIO.cleanup()
    print("GPIO cleanup complete.")
