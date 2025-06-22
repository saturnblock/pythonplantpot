import RPi.GPIO as GPIO
import time
import math
import busio
import board
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import threading

# Globale Konstanten für Hardware-Parameter
TANK_VOLUME = 500  # Tankvolumen in ml bei 100% Füllstand
PUMP_TIME_ONE_ML = 0.4  # Zeit in Sekunden, um 1 ml Wasser zu pumpen
ADC_MAX_VALUE = 26500  # Maximaler Rohwert des ADS1115

class ADS1115:
    """
    Klasse zur Interaktion mit dem ADS1115 ADC-Wandler über I2C.
    """
    def __init__(self):
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)
            self.ads = ADS.ADS1115(self.i2c)
            print("ADS1115 initialisiert.")
        except Exception as e:
            print(f"Fehler bei der Initialisierung des ADS1115: {e}")
            self.ads = None

    def get_value(self, channel_name):
        """
        Liest den Analogwert vom angegebenen ADC-Kanal.
        """
        if not self.ads:
            print("ADS1115 ist nicht verfügbar.")
            return -1

        read_channel = None
        if channel_name == "P0":
            read_channel = AnalogIn(self.ads, ADS.P0)
        elif channel_name == "P1":
            read_channel = AnalogIn(self.ads, ADS.P1)
        # Weitere Kanäle bei Bedarf hinzufügen
        else:
            print(f"Fehler: Ungültiger Kanal '{channel_name}'.")
            return -1
        return read_channel.value

    def moisture_sensor_status(self):
        """
        Liest den Feuchtigkeitssensorwert und wandelt ihn in Prozent um.
        """
        value = self.get_value("P0")
        if value == -1: return 0
        moisture_percentage = math.floor((value / ADC_MAX_VALUE) * 100)
        return max(0, min(100, moisture_percentage))

    def tank_level(self):
        """
        Liest den Tankfüllstandssensorwert und wandelt ihn in Prozent um.
        """
        value = self.get_value("P1")
        if value == -1: return 0
        tank_percentage = math.floor(((value / ADC_MAX_VALUE) * 100))
        return max(0, min(100, tank_percentage))

    def tank_level_ml(self):
        """
        Berechnet das verbleibende Tankvolumen in Millilitern.
        """
        # Annahme: Diese Funktion sollte das tatsächliche Volumen zurückgeben.
        # Die 2000 im Originalcode waren wahrscheinlich ein Platzhalter.
        # Korrekte Berechnung basierend auf dem Prozentsatz:
        return (self.tank_level() / 100) * TANK_VOLUME


class RotaryEncoder:
    """
    Klasse zur Interaktion mit einem KY-040 Drehgeber.
    """
    def __init__(self, menu_system_instance, clockPin=5, dataPin=6, switchPin=13):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        self.clockPin = clockPin
        self.dataPin = dataPin
        self.switchPin = switchPin
        self.lock = False
        self.menu_system = menu_system_instance

        GPIO.setup(clockPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(dataPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(switchPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def time_thread_encoder_func(self):
        time.sleep(0.2)
        self.lock = False

    def start_thread(self):
        GPIO.add_event_detect(self.clockPin, GPIO.FALLING, callback=self._clock_callback, bouncetime=50)
        GPIO.add_event_detect(self.switchPin, GPIO.FALLING, callback=self._switch_callback, bouncetime=300)
        print("Rotary Encoder Event-Erkennung gestartet.")

    def stop_thread(self):
        GPIO.remove_event_detect(self.clockPin)
        GPIO.remove_event_detect(self.switchPin)
        print("Rotary Encoder Event-Erkennung gestoppt.")

    def _clock_callback(self, pin):
        if not self.lock:
            self.lock = True
            if GPIO.input(self.dataPin) == 1:
                if self.menu_system: self.menu_system.navigate('right')
            else:
                if self.menu_system: self.menu_system.navigate('left')
            threading.Thread(target=self.time_thread_encoder_func, daemon=True).start()

    def _switch_callback(self, pin):
        if GPIO.input(self.switchPin) == 0:
            if self.menu_system: self.menu_system.confirm_selection()


class Pump:
    """
    Klasse zur Steuerung einer 12V Rohrpumpe.
    """
    def __init__(self, pumpPin=21):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        self.pumpPin = pumpPin
        GPIO.setup(self.pumpPin, GPIO.OUT, initial=GPIO.LOW)
        print(f"Pumpe auf Pin {self.pumpPin} initialisiert.")

    def pump_timer(self, watering_amount_ml):
        """
        Steuert die Pumpe für eine Dauer basierend auf der Wassermenge.
        """
        duration = watering_amount_ml * PUMP_TIME_ONE_ML
        print(f"Pumpe startet für {duration:.2f} Sekunden, um {watering_amount_ml} ml zu liefern.")
        GPIO.output(self.pumpPin, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(self.pumpPin, GPIO.LOW)
        print("Pumpe gestoppt.")

    def pump_for_duration(self, duration_s):
        """
        NEU: Lässt die Pumpe für eine angegebene Anzahl von Sekunden laufen.
        """
        if duration_s <= 0:
            return
        print(f"Pumpe startet für {duration_s} Sekunden (manueller Befehl).")
        GPIO.output(self.pumpPin, GPIO.HIGH)
        time.sleep(duration_s)
        GPIO.output(self.pumpPin, GPIO.LOW)
        print("Pumpe nach manueller Zeit gestoppt.")


    def start_pump_automatic(self, watering_amount_ml, precheck_instance):
        """
        Startet die automatische Bewässerung nach Vorabprüfungen.
        """
        if precheck_instance.water_tank(watering_amount_ml) and precheck_instance.moisture_sensor():
            print("Vorabprüfungen bestanden. Starte automatischen Pumpenbetrieb.")
            threading.Thread(target=self.pump_timer, args=(watering_amount_ml,), daemon=True).start()
        else:
            print("Automatische Bewässerung kann nicht gestartet werden.")

    def start_pump_manual(self):
        """
        Schaltet die Pumpe manuell ein.
        """
        print("Manuelle Pumpe AN.")
        GPIO.output(self.pumpPin, GPIO.HIGH)

    def stop_pump_manual(self):
        """
        Schaltet die Pumpe manuell aus.
        """
        print("Manuelle Pumpe AUS.")
        GPIO.output(self.pumpPin, GPIO.LOW)


class PreWateringCheck:
    """
    Klasse für Vorabprüfungen vor der automatischen Bewässerung.
    """
    def __init__(self, ads_instance):
        self.ads1115 = ads_instance

    def water_tank(self, watering_amount_ml):
        """
        Überprüft, ob genügend Wasser im Tank ist.
        """
        current_tank_ml = self.ads1115.tank_level_ml()
        if current_tank_ml >= watering_amount_ml:
            return True
        else:
            print(f"Tankfüllstand NIEDRIG: {current_tank_ml:.2f} ml verfügbar, benötigt {watering_amount_ml} ml.")
            return False

    def moisture_sensor(self, moisture_max_threshold=30, moisture_sensor_use=1):
        """
        Überprüft, ob der Boden trocken genug ist.
        """
        if moisture_sensor_use == 0:
            return True

        current_moisture = self.ads1115.moisture_sensor_status()
        # Die Logik hier wurde umgedreht, um mit der UI übereinzustimmen:
        # Es wird gegossen, wenn die Feuchtigkeit UNTER dem Schwellenwert liegt.
        if current_moisture < moisture_max_threshold:
            return True
        else:
            print(f"Boden zu feucht: {current_moisture}% (Schwelle: < {moisture_max_threshold}%).")
            return False
