import json
import time
import threading
import sys
import os
from datetime import datetime, timedelta


# Importiere die Hardware-Utilities
try:
    from pi_hardware_utils import ADS1115, Pump, PreWateringCheck, TANK_VOLUME
except ImportError:
    print("Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.")
    sys.exit(1)

# --- Globale Konfiguration und Statusdateien ---
CONFIG_FILE = 'config.json'
WATERING_STATUS_FILE = 'watering_status.json'

# Standardwerte für die Pflanzenbewässerung
DEFAULT_CONFIG = {
    "wateringtimer": 60,
    "wateringamount": 20,
    "moisturemax": 50,
    "moisturesensoruse": 1
}

# Globale Variablen für Konfiguration und Status
config = {}
watering_status = {
    "last_watering_time": None,
    "estimated_next_watering_time": None,
    "remaining_watering_cycles": 0,
    "current_timer_remaining_s": 0
}

# --- Funktionen zum Laden/Speichern von Konfiguration und Status ---
def load_config_for_system():
    """Lädt die Konfiguration aus der config.json-Datei für das Hauptsystem."""
    global config
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                config = data[0]
            else:
                config = DEFAULT_CONFIG
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"Warnung: '{CONFIG_FILE}' nicht gefunden oder beschädigt. Verwende Standardwerte.")
        config = DEFAULT_CONFIG

def load_watering_status():
    """Lädt den Bewässerungsstatus aus der watering_status.json-Datei."""
    global watering_status
    try:
        with open(WATERING_STATUS_FILE, 'r') as f:
            data = json.load(f)
            watering_status.update(data)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"'{WATERING_STATUS_FILE}' nicht gefunden. Initialisiere Status.")
        initialize_watering_status()

def save_watering_status():
    """Speichert den aktuellen Bewässerungsstatus in der watering_status.json-Datei."""
    try:
        with open(WATERING_STATUS_FILE, 'w') as f:
            json.dump(watering_status, f, indent=4)
    except Exception as e:
        print(f"Fehler beim Speichern des Bewässerungsstatus: {e}")

def initialize_watering_status():
    """Initialisiert den Bewässerungsstatus."""
    global watering_status
    load_config_for_system()
    watering_amount = config.get("wateringamount", DEFAULT_CONFIG["wateringamount"])
    watering_timer = config.get("wateringtimer", DEFAULT_CONFIG["wateringtimer"])

    if watering_amount > 0:
        watering_status["remaining_watering_cycles"] = int(TANK_VOLUME / watering_amount)
    else:
        watering_status["remaining_watering_cycles"] = 0

    current_time = time.time()
    watering_status["last_watering_time"] = current_time
    watering_status["estimated_next_watering_time"] = current_time + watering_timer
    watering_status["current_timer_remaining_s"] = watering_timer
    save_watering_status()
    print("Bewässerungsstatus initialisiert.")


class WateringControl:
    """
    Hauptsteuerung für die Bewässerung der Pflanze.
    """
    def __init__(self, pump_instance, precheck_instance):
        self._timer_thread = None
        self._stop_thread = threading.Event()
        self.pump = pump_instance
        self.prewatercheck = precheck_instance
        self.last_manual_request_ts = 0
        self.last_repot_request_ts = 0

    def process_config_requests(self):
        """
        Überprüft die config.json auf Anfragen von der UI und führt sie aus.
        """
        try:
            with open(CONFIG_FILE, 'r') as f:
                full_config_data = json.load()

            if not isinstance(full_config_data, list) or not full_config_data:
                return

            local_config = full_config_data[0]
            config_changed = False

            # Manuelle Pump-Anfrage prüfen
            pump_request = local_config.get("manual_pump_request")
            if pump_request and pump_request.get("timestamp", 0) > self.last_manual_request_ts:
                print("Neue manuelle Pump-Anfrage erhalten.")
                amount = pump_request.get("amount_ml", 0)
                if amount > 0:
                    self.pump.pump_timer(amount)
                self.last_manual_request_ts = pump_request["timestamp"]
                del local_config["manual_pump_request"]
                config_changed = True

            # Umtopf-Anfrage prüfen
            repot_request = local_config.get("repot_reset_request")
            if repot_request and repot_request.get("timestamp", 0) > self.last_repot_request_ts:
                print("Neue Umtopf-Anfrage erhalten.")
                initialize_watering_status()
                # Hier könnte man den Haupt-Timer neu starten, falls gewünscht
                self.last_repot_request_ts = repot_request["timestamp"]
                del local_config["repot_reset_request"]
                config_changed = True

            # Wenn eine Anfrage bearbeitet wurde, die config.json bereinigen
            if config_changed:
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(full_config_data, f, indent=4)
                print("Konfigurationsdatei nach Anfrage-Verarbeitung bereinigt.")

        except (FileNotFoundError, json.JSONDecodeError):
            pass # Datei existiert nicht oder ist ungültig, wird beim nächsten Mal erneut versucht.
        except Exception as e:
            print(f"Unerwarteter Fehler bei der Anfrage-Verarbeitung: {e}")

    def run_timer_loop(self):
        """
        Die Hauptschleife für die automatische Bewässerung.
        """
        global watering_status, config

        load_config_for_system()
        current_timer = config.get("wateringtimer", DEFAULT_CONFIG["wateringtimer"])
        print(f"Automatischer Bewässerungs-Timer gestartet für {current_timer} Sekunden.")

        while not self._stop_thread.is_set():
            # Aktuellen Timer-Status für die UI speichern
            next_watering_time = watering_status.get("estimated_next_watering_time", time.time())
            remaining_seconds = max(0, next_watering_time - time.time())
            watering_status["current_timer_remaining_s"] = remaining_seconds
            save_watering_status()

            # Prüfe auf UI-Anfragen
            self.process_config_requests()

            if remaining_seconds <= 0:
                print("Timer abgelaufen. Versuche automatische Bewässerung.")
                load_config_for_system() # Neueste Einstellungen laden
                watering_amount = config.get("wateringamount", DEFAULT_CONFIG["wateringamount"])
                moisture_max = config.get("moisturemax", DEFAULT_CONFIG["moisturemax"])
                sensor_use = config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"])

                if watering_status.get("remaining_watering_cycles", 0) > 0:
                    if self.prewatercheck.water_tank(watering_amount) and \
                            self.prewatercheck.moisture_sensor(moisture_max, sensor_use):
                        print("Vorabprüfungen bestanden. Starte automatischen Pumpenbetrieb.")
                        self.pump.pump_timer(watering_amount)
                        watering_status["last_watering_time"] = time.time()
                        watering_status["remaining_watering_cycles"] -= 1
                    else:
                        print("Bedingungen für autom. Bewässerung nicht erfüllt (Tank/Feuchtigkeit).")
                else:
                    print("Keine Gießzyklen mehr verfügbar (Tank als leer angenommen).")

                # Nächste Bewässerung planen und Timer neu starten
                new_timer_duration = config.get("wateringtimer", DEFAULT_CONFIG["wateringtimer"])
                watering_status["estimated_next_watering_time"] = time.time() + new_timer_duration
                save_watering_status()

            time.sleep(1) # Schleifenintervall

        print("Das automatische Bewässerungsprogramm wurde gestoppt.")

    def start(self):
        if self._timer_thread and self._timer_thread.is_alive():
            print("Automatisches Bewässerungsprogramm läuft bereits.")
            return

        load_config_for_system()
        if config.get("wateringtimer", 0) <= 0:
            print("Bewässerungs-Timer ist nicht gesetzt. Automatische Bewässerung kann nicht starten.")
            return

        self._stop_thread.clear()
        if watering_status.get("last_watering_time") is None or watering_status.get("remaining_watering_cycles", 0) == 0:
            initialize_watering_status()

        print("Starte automatisches Bewässerungsprogramm...")
        self._timer_thread = threading.Thread(target=self.run_timer_loop, daemon=True)
        self._timer_thread.start()

    def stop(self):
        if self._timer_thread and self._timer_thread.is_alive():
            print("Stoppe automatisches Bewässerungsprogramm...")
            self._stop_thread.set()
            self._timer_thread.join(timeout=2) # Warte kurz auf sauberes Beenden
        else:
            print("Automatisches Bewässerungsprogramm läuft nicht.")

# --- Hauptteil der Datei ---
if __name__ == "__main__":
    ads1115 = None
    wateringcontrol = None
    try:
        # Konfiguration und Status laden/initialisieren
        load_config_for_system()
        load_watering_status()

        # Hardware initialisieren
        ads1115 = ADS1115()
        pump = Pump()
        prewatercheck = PreWateringCheck(ads1115)
        wateringcontrol = WateringControl(pump, prewatercheck)

        print("\n--- Start des Hauptbewässerungssystems ---")
        wateringcontrol.start()
        print("Automatisches Bewässerungsprogramm läuft im Hintergrund.")
        print("Drücken Sie Strg+C, um das Programm zu beenden.")

        # Hauptschleife nur noch für Anfragen-Polling, falls der Timer-Thread nicht läuft
        while True:
            if not wateringcontrol._timer_thread or not wateringcontrol._timer_thread.is_alive():
                # Der Haupt-Timer-Thread ist nicht aktiv, also hier auf Anfragen prüfen.
                wateringcontrol.process_config_requests()
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nProgramm durch Benutzer beendet (Strg+C).")
    except Exception as e:
        print(f"\nEin Fehler ist während der Ausführung aufgetreten: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if wateringcontrol:
            wateringcontrol.stop()
        import RPi.GPIO as GPIO
        GPIO.cleanup()
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")
