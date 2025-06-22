import json
import time
import threading
import sys
import os
from datetime import datetime, timedelta

# Importiere die Hardware-Utilities
try:
    # WICHTIG: Stellen Sie sicher, dass pi_hardware_utils.py die neue Methode
    # pump_for_duration(self, duration_s) in der Pump-Klasse enthält.
    from pi_hardware_utils import ADS1115, Pump, PreWateringCheck, TANK_VOLUME
except ImportError:
    print("Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.")
    print("Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
    sys.exit(1)

# --- Globale Konfiguration und Statusdateien ---
CONFIG_FILE = 'config.json'
PUMP_COMMAND_FILE = 'pump_command.json'
WATERING_STATUS_FILE = 'watering_status.json'

# Standardwerte für die Pflanzenbewässerung
DEFAULT_CONFIG = {
    "wateringtimer": 60,
    "wateringamount": 20,
    "moisturemax": 50,
    "moisturesensoruse": 1
}

# Globale Variablen
wateringtimer = DEFAULT_CONFIG["wateringtimer"]
wateringamount = DEFAULT_CONFIG["wateringamount"]
moisturemax = DEFAULT_CONFIG["moisturemax"]
moisturesensoruse = DEFAULT_CONFIG["moisturesensoruse"]

watering_status = {
    "last_watering_time": None,
    "estimated_next_watering_time": None,
    "remaining_watering_cycles": 0,
    "current_timer_remaining_s": 0
}

# --- Funktionen zum Laden/Speichern ---
def load_config_for_system():
    """Lädt die Konfiguration für das Hauptsystem."""
    global wateringtimer, wateringamount, moisturemax, moisturesensoruse
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)[0]
            wateringtimer = config.get("wateringtimer", DEFAULT_CONFIG["wateringtimer"])
            wateringamount = config.get("wateringamount", DEFAULT_CONFIG["wateringamount"])
            moisturemax = config.get("moisturemax", DEFAULT_CONFIG["moisturemax"])
            moisturesensoruse = config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"])
    except (FileNotFoundError, json.JSONDecodeError, IndexError):
        print(f"Warnung: '{CONFIG_FILE}' nicht gefunden oder fehlerhaft. Verwende Standardwerte.")

def load_watering_status():
    """Lädt den Bewässerungsstatus."""
    global watering_status
    try:
        with open(WATERING_STATUS_FILE, 'r') as f:
            data = json.load(f)
            for key in watering_status:
                if key in data:
                    watering_status[key] = data[key]
            print("Bewässerungsstatus erfolgreich geladen.")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        print(f"Warnung: '{WATERING_STATUS_FILE}' nicht gefunden. Initialisiere Status.")
        initialize_watering_status()

def save_watering_status():
    """Speichert den Bewässerungsstatus."""
    try:
        with open(WATERING_STATUS_FILE, 'w') as f:
            json.dump(watering_status, f, indent=4)
    except Exception as e:
        print(f"Fehler beim Speichern des Bewässerungsstatus: {e}")

def initialize_pump_command_file():
    """Stellt sicher, dass die Befehlsdatei existiert und leer ist."""
    try:
        with open(PUMP_COMMAND_FILE, 'w') as f:
            json.dump({"action": "none"}, f)
        print(f"'{PUMP_COMMAND_FILE}' initialisiert.")
    except Exception as e:
        print(f"Fehler beim Initialisieren von '{PUMP_COMMAND_FILE}': {e}")

def initialize_watering_status():
    """Initialisiert den Bewässerungsstatus."""
    global watering_status
    load_config_for_system()
    if wateringamount > 0:
        watering_status["remaining_watering_cycles"] = int(TANK_VOLUME / wateringamount)
    else:
        watering_status["remaining_watering_cycles"] = 0
    watering_status["last_watering_time"] = time.time()
    watering_status["estimated_next_watering_time"] = time.time() + wateringtimer
    watering_status["current_timer_remaining_s"] = wateringtimer
    save_watering_status()
    print("Bewässerungsstatus initialisiert.")

class WateringControl:
    """Hauptsteuerung für die Bewässerung."""
    def __init__(self, pump_instance, precheck_instance):
        self._timer_thread = None
        self._stop_thread = False
        self.pump = pump_instance
        self.prewatercheck = precheck_instance

    def run_timer_loop(self):
        """Hauptschleife für die automatische Bewässerung."""
        global wateringtimer, wateringamount, moisturemax, moisturesensoruse, watering_status
        load_config_for_system()
        current_timer = wateringtimer
        print(f"Automatischer Bewässerungs-Timer gestartet ({current_timer}s).")
        while current_timer >= 0 and not self._stop_thread:
            watering_status["current_timer_remaining_s"] = current_timer
            save_watering_status()
            self.process_manual_pump_commands()
            time.sleep(1)
            current_timer -= 1

        if not self._stop_thread:
            print("Timer abgelaufen. Prüfe Bedingungen für automatische Bewässerung.")
            if watering_status["remaining_watering_cycles"] > 0:
                if self.prewatercheck.water_tank(wateringamount) and \
                        self.prewatercheck.moisture_sensor(moisturemax, moisturesensoruse):
                    print("Vorabprüfungen bestanden. Starte automatischen Pumpenbetrieb.")
                    self.pump.pump_timer(wateringamount)
                    watering_status["last_watering_time"] = time.time()
                    watering_status["remaining_watering_cycles"] -= 1
                    print(f"Verbleibende Gießzyklen: {watering_status['remaining_watering_cycles']}")
                else:
                    print("Bedingungen nicht erfüllt. Automatische Bewässerung übersprungen.")
            else:
                print("Keine Gießzyklen mehr verfügbar (Tank leer).")

            watering_status["estimated_next_watering_time"] = time.time() + wateringtimer
            save_watering_status()
            self.run_timer_loop()
        else:
            print("Automatisches Bewässerungsprogramm gestoppt.")

    def process_manual_pump_commands(self):
        """Überprüft und verarbeitet Befehle aus der pump_command.json."""
        try:
            with open(PUMP_COMMAND_FILE, 'r') as f:
                command = json.load(f)

            action = command.get("action")
            if action == "none":
                return

            # Befehl gefunden, sofort zur Verarbeitung zurücksetzen
            with open(PUMP_COMMAND_FILE, 'w') as f:
                json.dump({"action": "none"}, f)

            if action == "pump_manual":
                amount_ml = command.get("amount_ml", 0)
                if amount_ml > 0:
                    print(f"Manueller Pumpenbefehl empfangen: {amount_ml} ml.")
                    self.pump.pump_timer(amount_ml)
                print("Manueller Pumpenbefehl ausgeführt.")

            elif action == "pump_timed": # NEU: Zeitgesteuerter Pumpenbefehl
                duration_s = command.get("duration_s", 0)
                if duration_s > 0:
                    print(f"Zeitgesteuerter Pumpenbefehl empfangen: {duration_s} s.")
                    # Führe die Pumpenaktion in einem eigenen Thread aus,
                    # um den Hauptthread nicht zu blockieren.
                    threading.Thread(target=self.pump.pump_for_duration, args=(duration_s,), daemon=True).start()
                print("Zeitgesteuerter Pumpenbefehl ausgeführt.")

            elif action == "repot_reset":
                print("Umtopf-Reset-Befehl empfangen. Initialisiere Gießstatus.")
                initialize_watering_status()
                print("Umtopf-Reset ausgeführt.")

        except (FileNotFoundError, json.JSONDecodeError):
            pass
        except Exception as e:
            print(f"Unerwarteter Fehler bei der Befehlsverarbeitung: {e}")

    def start(self):
        """Startet das automatische Bewässerungsprogramm."""
        load_config_for_system()
        if wateringtimer > 0:
            self._stop_thread = False
            if watering_status.get("last_watering_time") is None:
                initialize_watering_status()
            print("Starte automatisches Bewässerungsprogramm...")
            self._timer_thread = threading.Thread(target=self.run_timer_loop, daemon=True)
            self._timer_thread.start()
        else:
            print("Timer ist auf 0 gesetzt. Automatikmodus startet nicht.")

    def stop(self):
        """Stoppt das automatische Bewässerungsprogramm."""
        if self._timer_thread and self._timer_thread.is_alive():
            print("Stoppe automatisches Bewässerungsprogramm...")
            self._stop_thread = True

# --- Hauptteil ---
if __name__ == "__main__":
    load_config_for_system()
    initialize_pump_command_file()
    load_watering_status()

    ads1115 = ADS1115()
    pump = Pump()
    prewatercheck = PreWateringCheck(ads1115)
    wateringcontrol = WateringControl(pump, prewatercheck)

    try:
        print("\n--- Hauptbewässerungssystem gestartet ---")
        wateringcontrol.start()
        print("System läuft. Drücken Sie Strg+C zum Beenden.")
        while True:
            wateringcontrol.process_manual_pump_commands()
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nProgramm durch Benutzer beendet.")
    except Exception as e:
        print(f"\nEin kritischer Fehler ist aufgetreten: {e}")
        import traceback
        traceback.print_exc()
    finally:
        wateringcontrol.stop()
        import RPi.GPIO as GPIO
        GPIO.cleanup()
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")

