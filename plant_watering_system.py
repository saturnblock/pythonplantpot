import json
import time
import threading
import sys

# Importiere die Hardware-Utilities
# Stelle sicher, dass pi_hardware_utils.py im selben Verzeichnis liegt oder im PYTHONPATH ist
try:
    from pi_hardware_utils import ADS1115, Pump, PreWateringCheck, TANK_VOLUME
except ImportError:
    print("Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.")
    print("Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
    sys.exit(1)

# --- Globale Konfiguration und Standardwerte ---
CONFIG_FILE = 'config.json'

# Standardwerte für die Pflanzenbewässerung (sollten mit denen in der UI übereinstimmen)
DEFAULT_CONFIG = {
    "wateringtimer": 3600,  # in s (1 Stunde)
    "wateringamount": 50,   # in ml
    "moisturemax": 30,      # in % (wenn Feuchtigkeit darunter, wird gegossen)
    "moisturesensoruse": 1  # 1 für aktiv, 0 für inaktiv
}

# Globale Variablen, die aus der Konfigurationsdatei geladen werden
wateringtimer = DEFAULT_CONFIG["wateringtimer"]
wateringamount = DEFAULT_CONFIG["wateringamount"]
moisturemax = DEFAULT_CONFIG["moisturemax"]
moisturesensoruse = DEFAULT_CONFIG["moisturesensoruse"]

# --- Funktionen zum Laden der Konfiguration ---
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
                print("System-Konfiguration erfolgreich geladen.")
            else:
                print(f"{CONFIG_FILE} ist leer oder hat ein unerwartetes Format. Verwende Standardwerte.")
                # Hier keine Speicherung, da die UI für die Speicherung zuständig ist
    except FileNotFoundError:
        print(f"{CONFIG_FILE} nicht gefunden. Verwende Standardwerte.")
    except json.JSONDecodeError:
        print(f"{CONFIG_FILE} ist beschädigt. Verwende Standardwerte.")
    except Exception as e:
        print(f"Unerwarteter Fehler beim Laden von {CONFIG_FILE} für das System: {e}. Verwende Standardwerte.")

class WateringControl:
    """
    Hauptsteuerung für die Bewässerung der Pflanze.
    """
    def __init__(self, pump_instance, precheck_instance):
        self._timer_thread = None
        self._stop_thread = False
        self.pump = pump_instance
        self.prewatercheck = precheck_instance
        self.last_watering_time = None # Speichert den Zeitpunkt der letzten Bewässerung

    def run_timer_loop(self):
        """
        Die Hauptschleife für die automatische Bewässerung, läuft auf einem Timer.
        """
        global wateringtimer, wateringamount, moisturemax, moisturesensoruse

        # Sicherstellen, dass die neuesten Konfigurationswerte verwendet werden
        load_config_for_system()

        timer = wateringtimer
        print(f"Automatischer Bewässerungs-Timer gestartet für {timer} Sekunden.")
        while timer >= 0 and not self._stop_thread:
            time.sleep(1)
            timer -= 1
            # print(f"Timer: {timer}s verbleibend") # Auskommentiert für weniger Konsolenausgabe

        if not self._stop_thread:
            print("Timer abgelaufen. Versuche automatische Bewässerung.")
            # Die Werte für die Vorabprüfung und die Pumpe kommen jetzt aus der globalen Konfiguration
            self.pump.start_pump_automatic(wateringamount, self.prewatercheck)
            self.last_watering_time = time.time() # Zeitpunkt der Bewässerung speichern
            self.run_timer_loop()  # Timer nach der Bewässerung neu starten
        else:
            print("Das automatische Bewässerungsprogramm wurde gestoppt.")

    def start(self):
        """
        Startet das automatische Bewässerungsprogramm.
        """
        global wateringtimer
        load_config_for_system() # Konfiguration vor dem Start aktualisieren

        if wateringtimer > 0:
            self._stop_thread = False
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
    # Konfiguration für das System laden
    load_config_for_system()

    # Hardware initialisieren
    ads1115 = ADS1115()
    pump = Pump()
    prewatercheck = PreWateringCheck(ads1115)
    wateringcontrol = WateringControl(pump, prewatercheck)

    try:
        print("\n--- Start des Hauptbewässerungssystems ---")
        print(f"Aktuelle Konfiguration: Intervall={wateringtimer}s, Menge={wateringamount}ml, Feuchtigkeit max={moisturemax}%, Sensor aktiv={moisturesensoruse}")

        # Starte das automatische Bewässerungsprogramm
        wateringcontrol.start()
        print("Automatisches Bewässerungsprogramm läuft im Hintergrund.")
        print("Drücken Sie Strg+C, um das Programm zu beenden.")

        # Hauptschleife, die das Programm am Laufen hält
        while True:
            time.sleep(1) # Halte das Hauptprogramm am Laufen

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
        # Wenn der Drehgeber im Hauptprogramm verwendet würde, müsste er hier gestoppt werden.
        # Da er jetzt in der UI-Datei ist, ist das hier nicht mehr nötig.
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")

