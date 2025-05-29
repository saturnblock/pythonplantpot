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
    print("Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
    sys.exit(1)

# --- Globale Konfiguration und Statusdateien ---
CONFIG_FILE = 'config.json'
PUMP_COMMAND_FILE = 'pump_command.json'
WATERING_STATUS_FILE = 'watering_status.json'

# Standardwerte für die Pflanzenbewässerung (sollten mit denen in der UI übereinstimmen)
DEFAULT_CONFIG = {
    "wateringtimer": 60,  # in s (1 Stunde)
    "wateringamount": 20,   # in ml
    "moisturemax": 50,      # in % (wenn Feuchtigkeit darunter, wird gegossen)
    "moisturesensoruse": 1  # 1 für aktiv, 0 für inaktiv
}

# Globale Variablen für die Konfiguration (aus config.json geladen)
wateringtimer = DEFAULT_CONFIG["wateringtimer"]
wateringamount = DEFAULT_CONFIG["wateringamount"]
moisturemax = DEFAULT_CONFIG["moisturemax"]
moisturesensoruse = DEFAULT_CONFIG["moisturesensoruse"]

# Globaler Status für die Bewässerung (aus watering_status.json geladen/gespeichert)
watering_status = {
    "last_watering_time": None, # Unix-Timestamp der letzten Bewässerung
    "estimated_next_watering_time": None, # Unix-Timestamp der nächsten geplanten Bewässerung
    "remaining_watering_cycles": 0, # Anzahl der Gießzyklen, die mit vollem Tank möglich sind
    "current_timer_remaining_s": 0 # Verbleibende Sekunden des aktuellen Timers
}

# --- Funktionen zum Laden/Speichern von Konfiguration und Status ---
def load_config_for_system():
    """Lädt die Konfiguration aus der config.json-Datei für das Hauptsystem."""
    global wateringtimer, wateringamount, moisturemax, moisturesensoruse
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                config = data[0]
                wateringtimer = config.get("wateringtimer", DEFAULT_CONFIG["wateringtimer"])
                wateringamount = config.get("wateringamount", DEFAULT_CONFIG["wateringamount"])
                moisturemax = config.get("moisturemax", DEFAULT_CONFIG["moisturemax"])
                moisturesensoruse = config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"])
            # print("System-Konfiguration erfolgreich geladen.") # Auskommentiert für weniger Konsolenausgabe
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        print(f"Fehler beim Laden von '{CONFIG_FILE}'. Verwende Standardwerte.")

def load_watering_status():
    """Lädt den Bewässerungsstatus aus der watering_status.json-Datei."""
    global watering_status
    try:
        with open(WATERING_STATUS_FILE, 'r') as f:
            data = json.load(f)
            # Überprüfe und aktualisiere nur erwartete Schlüssel
            for key in watering_status:
                if key in data:
                    watering_status[key] = data[key]
            print("Bewässerungsstatus erfolgreich geladen.")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        print(f"Fehler beim Laden von '{WATERING_STATUS_FILE}'. Initialisiere Status.")
        initialize_watering_status()

def save_watering_status():
    """Speichert den aktuellen Bewässerungsstatus in der watering_status.json-Datei."""
    try:
        with open(WATERING_STATUS_FILE, 'w') as f:
            json.dump(watering_status, f, indent=4)
        # print("Bewässerungsstatus erfolgreich gespeichert.") # Auskommentiert für weniger Konsolenausgabe
    except Exception as e:
        print(f"Fehler beim Speichern des Bewässerungsstatus in '{WATERING_STATUS_FILE}': {e}")

def initialize_pump_command_file():
    """Stellt sicher, dass die pump_command.json-Datei existiert und leer ist."""
    if not os.path.exists(PUMP_COMMAND_FILE):
        with open(PUMP_COMMAND_FILE, 'w') as f:
            json.dump({"action": "none"}, f)
        print(f"'{PUMP_COMMAND_FILE}' erstellt.")
    else:
        try:
            with open(PUMP_COMMAND_FILE, 'r') as f:
                data = json.load(f)
                if not isinstance(data, dict) or "action" not in data:
                    raise ValueError("Ungültiges Format")
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            print(f"'{PUMP_COMMAND_FILE}' ist beschädigt oder hat ein ungültiges Format. Setze zurück.")
            with open(PUMP_COMMAND_FILE, 'w') as f:
                json.dump({"action": "none"}, f)

def initialize_watering_status():
    """Initialisiert den Bewässerungsstatus, insbesondere nach einem Umtopfen oder Start."""
    global watering_status, wateringamount

    # Lade die aktuelle Konfiguration, um die Gießmenge zu erhalten
    load_config_for_system()

    # Berechne die initialen Gießzyklen basierend auf dem vollen Tankvolumen
    if wateringamount > 0:
        watering_status["remaining_watering_cycles"] = int(TANK_VOLUME / wateringamount)
    else:
        watering_status["remaining_watering_cycles"] = 0

    watering_status["last_watering_time"] = time.time() # Setze auf jetzt
    watering_status["estimated_next_watering_time"] = time.time() + wateringtimer
    watering_status["current_timer_remaining_s"] = wateringtimer
    save_watering_status()
    print("Bewässerungsstatus initialisiert.")


class WateringControl:
    """
    Hauptsteuerung für die Bewässerung der Pflanze.
    """
    def __init__(self, pump_instance, precheck_instance):
        self._timer_thread = None
        self._stop_thread = False
        self.pump = pump_instance
        self.prewatercheck = precheck_instance

    def run_timer_loop(self):
        """
        Die Hauptschleife für die automatische Bewässerung, läuft auf einem Timer.
        """
        global wateringtimer, wateringamount, moisturemax, moisturesensoruse, watering_status

        # Sicherstellen, dass die neuesten Konfigurationswerte verwendet werden
        load_config_for_system()

        current_timer = wateringtimer # Initialisiere den Timer mit dem konfigurierten Wert

        print(f"Automatischer Bewässerungs-Timer gestartet für {current_timer} Sekunden.")
        while current_timer >= 0 and not self._stop_thread:
            # Aktualisiere den verbleibenden Timer-Wert im Status
            watering_status["current_timer_remaining_s"] = current_timer
            save_watering_status() # Speichere den Status häufig, damit die GUI ihn lesen kann

            self.process_manual_pump_commands() # Überprüfe auch während des Timers auf manuelle Pumpenbefehle
            time.sleep(1)
            current_timer -= 1

        if not self._stop_thread:
            print("Timer abgelaufen. Versuche automatische Bewässerung.")
            # Die Werte für die Vorabprüfung und die Pumpe kommen jetzt aus der globalen Konfiguration

            # Prüfe, ob noch Gießzyklen übrig sind, bevor tatsächlich versucht wird zu gießen
            if watering_status["remaining_watering_cycles"] > 0:
                if self.prewatercheck.water_tank(wateringamount) and \
                        self.prewatercheck.moisture_sensor(moisturemax, moisturesensoruse):

                    print("Vorabprüfungen bestanden. Starte automatischen Pumpenbetrieb.")
                    self.pump.pump_timer(wateringamount)

                    # Aktualisiere den Status nach erfolgreichem Gießen
                    watering_status["last_watering_time"] = time.time()
                    watering_status["remaining_watering_cycles"] -= 1 # Zähle den Zyklus herunter
                    print(f"Verbleibende Gießzyklen: {watering_status['remaining_watering_cycles']}")
                else:
                    print("Automatische Bewässerung konnte nicht durchgeführt werden (Tank leer oder Boden zu feucht).")
            else:
                print("Keine Gießzyklen mehr verfügbar (Tank als leer angenommen).")

            # Unabhängig davon, ob gegossen wurde oder nicht, planen wir die nächste Bewässerung
            watering_status["estimated_next_watering_time"] = time.time() + wateringtimer
            save_watering_status() # Speichere den aktualisierten Status

            self.run_timer_loop()  # Timer nach der Bewässerung neu starten
        else:
            print("Das automatische Bewässerungsprogramm wurde gestoppt.")

    def process_manual_pump_commands(self):
        """
        Überprüft die pump_command.json-Datei auf manuelle Pumpenbefehle und führt sie aus.
        """
        try:
            with open(PUMP_COMMAND_FILE, 'r') as f:
                command = json.load(f)

            if command.get("action") == "pump_manual":
                amount_ml = command.get("amount_ml", 0)
                if amount_ml > 0:
                    print(f"Manueller Pumpenbefehl empfangen: {amount_ml} ml.")
                    self.pump.pump_timer(amount_ml)

                # Befehl nach Ausführung zurücksetzen
                with open(PUMP_COMMAND_FILE, 'w') as f:
                    json.dump({"action": "none"}, f)
                print("Manueller Pumpenbefehl ausgeführt und zurückgesetzt.")

            elif command.get("action") == "repot_reset":
                print("Umtopf-Reset-Befehl empfangen. Initialisiere Gießstatus neu.")
                initialize_watering_status() # Setzt den Zähler und Timer zurück

                with open(PUMP_COMMAND_FILE, 'w') as f:
                    json.dump({"action": "none"}, f)
                print("Umtopf-Reset ausgeführt und Befehl zurückgesetzt.")

        except (FileNotFoundError, json.JSONDecodeError) as e:
            pass # Ignoriere Fehler, da die Datei möglicherweise gerade von der GUI geschrieben wird
        except Exception as e:
            print(f"Unerwarteter Fehler beim Verarbeiten manueller Pumpenbefehle: {e}")


    def start(self):
        """
        Startet das automatische Bewässerungsprogramm.
        """
        global wateringtimer
        load_config_for_system() # Konfiguration vor dem Start aktualisieren

        if wateringtimer > 0:
            self._stop_thread = False
            # Initialisiere den Status beim Start des automatischen Programms, falls er nicht gesetzt ist
            if watering_status["last_watering_time"] is None or watering_status["remaining_watering_cycles"] == 0:
                initialize_watering_status()

            print("Starte automatisches Bewässerungsprogramm...")
            self._timer_thread = threading.Thread(target=self.run_timer_loop, daemon=True)
            self._timer_thread.start()
        else:
            print("Bewässerungs-Timer ist nicht gesetzt. Automatische Bewässerung kann nicht starten.")

    def stop(self):
        """
        Stoppt das automatische Bewässerungsprogramm.
        """
        if self._timer_thread and self._timer_thread.is_alive():
            print("Stoppe automatisches Bewässerungsprogramm...")
            self._stop_thread = True
            # Es kann bis zu 1 Sekunde dauern, bis der Thread das Stoppsignal erkennt
        else:
            print("Automatisches Bewässerungsprogramm läuft nicht.")

# --- Hauptteil der Datei ---
if __name__ == "__main__":
    # Konfiguration und Status laden/initialisieren
    load_config_for_system()
    initialize_pump_command_file()
    load_watering_status() # Lade den Status beim Start

    # Hardware initialisieren
    ads1115 = ADS1115()
    pump = Pump() # Nur hier wird die Pumpe initialisiert
    prewatercheck = PreWateringCheck(ads1115)
    wateringcontrol = WateringControl(pump, prewatercheck)

    try:
        print("\n--- Start des Hauptbewässerungssystems ---")
        print(f"Aktuelle Konfiguration: Intervall={wateringtimer}s, Menge={wateringamount}ml, Feuchtigkeit max={moisturemax}%, Sensor aktiv={moisturesensoruse}")
        print(f"Aktueller Bewässerungsstatus: {watering_status}")

        # Starte das automatische Bewässerungsprogramm
        wateringcontrol.start()
        print("Automatisches Bewässerungsprogramm läuft im Hintergrund.")
        print("Drücken Sie Strg+C, um das Programm zu beenden.")

        # Hauptschleife, die das Programm am Laufen hält
        while True:
            # Überprüfe auch im Hauptthread auf manuelle Pumpenbefehle,
            # falls der Timer-Loop gerade nicht aktiv ist oder für schnelle Reaktionen.
            wateringcontrol.process_manual_pump_commands()
            time.sleep(0.5) # Häufiger prüfen für schnellere Reaktion auf manuelle Befehle

    except KeyboardInterrupt:
        print("\nProgramm durch Benutzer beendet (Strg+C).")
    except Exception as e:
        print(f"\nEin Fehler ist während der Ausführung aufgetreten: {e}")
        import traceback
        traceback.print_exc() # Vollständigen Traceback für Debugging ausgeben
    finally:
        # Sicherstellen, dass das Bewässerungsprogramm gestoppt wird
        wateringcontrol.stop()
        # GPIO-Pins aufräumen
        import RPi.GPIO as GPIO # Sicherstellen, dass GPIO hier importiert ist
        GPIO.cleanup()
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")