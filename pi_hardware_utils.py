import RPi.GPIO as GPIO
import time
import math
import busio
import board
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import threading

# Globale Konstanten für Hardware-Parameter
# Diese können bei Bedarf in die config.json verschoben werden,
# wenn sie vom Benutzer konfigurierbar sein sollen.
TANK_VOLUME = 500  # Tankvolumen in ml bei 100% Füllstand
PUMP_TIME_ONE_ML = 0.4  # Zeit in Sekunden, um 1 ml Wasser zu pumpen
ADC_MAX_VALUE = 26500  # Maximaler Rohwert des ADS1115 bei Standardverstärkung (ca.)

class ADS1115:
    """
    Klasse zur Interaktion mit dem ADS1115 ADC-Wandler über I2C.
    Ermöglicht das Auslesen von analogen Sensoren wie Feuchtigkeit und Tankfüllstand.
    """
    def __init__(self):
        try:
            # Erstelle den I2C-Bus
            self.i2c = busio.I2C(board.SCL, board.SDA)
            # Erstelle das ADC-Objekt mit dem I2C-Bus
            self.ads = ADS.ADS1115(self.i2c)
            print("ADS1115 initialisiert.")
        except Exception as e:
            print(f"Fehler bei der Initialisierung des ADS1115: {e}")
            print("Stellen Sie sicher, dass der ADS1115 korrekt angeschlossen ist und I2C aktiviert ist.")
            self.ads = None # Setze ads auf None, um weitere Fehler zu vermeiden

    def get_value(self, channel_name):
        """
        Liest den Analogwert vom angegebenen ADC-Kanal.
        Kanäle werden als "P0", "P1", "P2", "P3" bezeichnet.
        Gibt -1 zurück, wenn der ADS1115 nicht initialisiert wurde oder ein ungültiger Kanal.
        """
        if not self.ads:
            print("ADS1115 ist nicht verfügbar. Kann keine Werte lesen.")
            return -1

        read_channel = None
        if channel_name == "P0":
            read_channel = AnalogIn(self.ads, ADS.P0)
        elif channel_name == "P1":
            read_channel = AnalogIn(self.ads, ADS.P1)
        elif channel_name == "P2":
            read_channel = AnalogIn(self.ads, ADS.P2)
        elif channel_name == "P3":
            read_channel = AnalogIn(self.ads, ADS.P3)
        else:
            print(f"Fehler: Ungültiger Kanal '{channel_name}' für ADS1115 angegeben.")
            return -1

        return read_channel.value if read_channel else -1

    def moisture_sensor_status(self):
        """
        Liest den Feuchtigkeitssensorwert von P0 und wandelt ihn in einen Prozentsatz um.
        Annahme: Höhere Sensorwerte bedeuten trockenere Erde.
        ADC_MAX_VALUE entspricht 0% Feuchtigkeit (vollständig trocken).
        0 entspricht 100% Feuchtigkeit (vollständig nass).
        """
        value = self.get_value("P0")
        if value == -1:
            return 0

        # Umgekehrte Skalierung: 0 (nass) bis ADC_MAX_VALUE (trocken)
        # moisture_percentage = 100 - (value / ADC_MAX_VALUE * 100)
        # Wenn der Sensor bei Trockenheit einen hohen Wert und bei Nässe einen niedrigen Wert liefert:
        # Beispiel: 26500 ist sehr trocken (0% Feuchtigkeit), 10000 ist sehr nass (100% Feuchtigkeit)
        # Dann wäre die Formel:
        # min_wet_value = 10000 # Beispielwert für "sehr nass"
        # max_dry_value = ADC_MAX_VALUE # Beispielwert für "sehr trocken"
        # moisture_level = 100 - ((value - min_wet_value) / (max_dry_value - min_wet_value)) * 100
        # Für die aktuelle Logik des Benutzers, die offenbar eine direkte Proportionalität annimmt:
        moisture_percentage = math.floor((value / ADC_MAX_VALUE) * 100)
        # Sicherstellen, dass der Wert zwischen 0 und 100 liegt
        return max(0, min(100, moisture_percentage))

    def tank_level(self):
        """
        Liest den Tankfüllstandssensorwert von P1 und wandelt ihn in einen Prozentsatz um.
        Annahme: Höhere Sensorwerte bedeuten volleren Tank.
        ADC_MAX_VALUE entspricht 100% Füllstand.
        0 entspricht 0% Füllstand.
        """
        value = self.get_value("P1")
        if value == -1:
            return 0
        tank_percentage = math.floor(((value / ADC_MAX_VALUE) * 100))
        # Sicherstellen, dass der Wert zwischen 0 und 100 liegt
        return max(0, min(100, tank_percentage))

    def tank_level_ml(self):
        """
        Berechnet das verbleibende Tankvolumen in Millilitern basierend auf dem Prozentsatz.
        """
        return 2000


class RotaryEncoder:
    """
    Klasse zur Interaktion mit einem KY-040 Drehgeber.
    Ruft Methoden eines übergebenen MenuSystem-Objekts auf.
    """
    def __init__(self, menu_system_instance, clockPin=5, dataPin=6, switchPin=13):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        self.clockPin = clockPin
        self.dataPin = dataPin
        self.switchPin = switchPin
        self.lock = False  # Sperrvariable zur Entprellung
        self.menu_system = menu_system_instance # Referenz zum MenuSystem

        # GPIO-Pins einrichten
        GPIO.setup(clockPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(dataPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(switchPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def time_thread_encoder_func(self):
        """
        Verzögerungsfunktion für die Entprellung des Drehgebers.
        """
        time.sleep(0.2)
        self.lock = False

    def start_thread(self):
        """
        Startet die Event-Erkennung für die Drehgeber-Pins.
        """
        GPIO.add_event_detect(self.clockPin, GPIO.FALLING, callback=self._clock_callback, bouncetime=50)
        GPIO.add_event_detect(self.switchPin, GPIO.FALLING, callback=self._switch_callback, bouncetime=300)
        print("Rotary Encoder Event-Erkennung gestartet.")

    def stop_thread(self):
        """
        Stoppt die Event-Erkennung für die Drehgeber-Pins.
        """
        GPIO.remove_event_detect(self.clockPin)
        GPIO.remove_event_detect(self.switchPin)
        print("Rotary Encoder Event-Erkennung gestoppt.")

    def _clock_callback(self, pin):
        """
        Callback-Funktion für die fallende Flanke des Clock-Pins.
        Bestimmt die Drehrichtung und ruft die entsprechende MenuSystem-Methode auf.
        """
        if not self.lock:
            self.lock = True
            if GPIO.input(self.dataPin) == 1:
                # Rechtsdrehung
                if self.menu_system:
                    self.menu_system.navigate('right')
            else:
                # Linksdrehung
                if self.menu_system:
                    self.menu_system.navigate('left')
            # Neuen Thread starten, um die Sperre nach einer Verzögerung aufzuheben
            threading.Thread(target=self.time_thread_encoder_func, daemon=True).start()

    def _switch_callback(self, pin):
        """
        Callback-Funktion für die fallende Flanke des Switch-Pins.
        Registriert einen Tastendruck und ruft die MenuSystem-Bestätigungsmethode auf.
        """
        if GPIO.input(self.switchPin) == 0: # Bestätigen, dass der Button noch gedrückt ist
            if self.menu_system:
                self.menu_system.confirm_selection()


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
        Steuert die Pumpe für eine Dauer basierend auf der gewünschten Wassermenge.
        """
        print(f"Pumpe startet für {watering_amount_ml * PUMP_TIME_ONE_ML:.2f} Sekunden, um {watering_amount_ml} ml zu liefern.")
        GPIO.output(self.pumpPin, GPIO.HIGH)
        time.sleep(watering_amount_ml * PUMP_TIME_ONE_ML)
        GPIO.output(self.pumpPin, GPIO.LOW)
        print("Pumpe gestoppt.")

    def start_pump_automatic(self, watering_amount_ml, precheck_instance):
        """
        Startet die automatische Bewässerung, wenn die Vorabprüfungen bestanden sind.
        """
        if precheck_instance.water_tank(watering_amount_ml) and precheck_instance.moisture_sensor():
            print("Vorabprüfungen bestanden. Starte automatischen Pumpenbetrieb.")
            threading.Thread(target=self.pump_timer, args=(watering_amount_ml,), daemon=True).start()
        else:
            print("Automatische Bewässerung kann nicht gestartet werden, da der Wassertank leer ist oder der Boden zu feucht ist.")

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
        Überprüft, ob genügend Wasser im Tank für die Bewässerungsmenge vorhanden ist.
        """
        current_tank_ml = self.ads1115.tank_level_ml()
        if current_tank_ml >= watering_amount_ml:
            # print(f"Tankfüllstand OK: {current_tank_ml:.2f} ml verfügbar, benötigt {watering_amount_ml} ml.")
            return True
        else:
            # print(f"Tankfüllstand NIEDRIG: {current_tank_ml:.2f} ml verfügbar, benötigt {watering_amount_ml} ml.")
            return False

    def moisture_sensor(self, moisture_max_threshold=30, moisture_sensor_use=1):
        """
        Überprüft, ob der Boden trocken genug für einen weiteren Bewässerungsvorgang ist.
        """
        if moisture_sensor_use == 0: # Wenn Feuchtigkeitssensor nicht verwendet wird, immer True zurückgeben
            # print("Feuchtigkeitssensor-Nutzung ist deaktiviert. Boden wird als trocken genug angenommen.")
            return True

        current_moisture = self.ads1115.moisture_sensor_status()
        if current_moisture >= moisture_max_threshold: # Annahme: 'moisture_max_threshold' ist der Schwellenwert für 'trocken genug'
            # print(f"Bodenfeuchtigkeit OK: {current_moisture}% (max. erlaubt: {moisture_max_threshold}%).")
            return True
        else:
            # print(f"Boden zu feucht: {current_moisture}% (max. erlaubt: {moisture_max_threshold}%).")
            return False

