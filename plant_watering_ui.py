import json
import time
import threading
import os
import sys

# Importiere die Hardware-Utilities
# Stelle sicher, dass pi_hardware_utils.py im selben Verzeichnis liegt oder im PYTHONPATH ist
try:
    from pi_hardware_utils import ADS1115, RotaryEncoder, Pump, PreWateringCheck, TANK_VOLUME
except ImportError:
    print("Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.")
    print("Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
    sys.exit(1)

# --- Globale Konfiguration und Standardwerte ---
CONFIG_FILE = 'config.json'

# Standardwerte für die Pflanzenbewässerung
DEFAULT_CONFIG = {
    "wateringtimer": 3600,  # in s (1 Stunde)
    "wateringamount": 50,   # in ml
    "moisturemax": 30,      # in % (wenn Feuchtigkeit darunter, wird gegossen)
    "moisturesensoruse": 1  # 1 für aktiv, 0 für inaktiv
}

current_config = {} # Wird beim Start aus config.json geladen

# --- Funktionen zum Laden/Speichern der Konfiguration ---
def load_config():
    """Lädt die Konfiguration aus der config.json-Datei."""
    global current_config
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                current_config = data[0]
                print("Konfiguration erfolgreich geladen.")
            else:
                print("config.json ist leer oder hat ein unerwartetes Format. Verwende Standardwerte.")
                current_config = DEFAULT_CONFIG
                save_config() # Speichere Standardwerte
    except FileNotFoundError:
        print(f"{CONFIG_FILE} nicht gefunden. Erstelle neue Datei mit Standardwerten.")
        current_config = DEFAULT_CONFIG
        save_config()
    except json.JSONDecodeError:
        print(f"{CONFIG_FILE} ist beschädigt. Erstelle neue Datei mit Standardwerten.")
        current_config = DEFAULT_CONFIG
        save_config()
    except Exception as e:
        print(f"Unerwarteter Fehler beim Laden von {CONFIG_FILE}: {e}. Verwende Standardwerte.")
        current_config = DEFAULT_CONFIG
        save_config()

def save_config():
    """Speichert die aktuelle Konfiguration in der config.json-Datei."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump([current_config], f, indent=4)
        print("Konfiguration erfolgreich gespeichert.")
    except Exception as e:
        print(f"Fehler beim Speichern der Konfiguration in {CONFIG_FILE}: {e}")

# --- Menüsystem-Klasse ---
class MenuSystem:
    def __init__(self, ads_instance, pump_instance, precheck_instance):
        self.ads1115 = ads_instance
        self.pump = pump_instance
        self.prewatercheck = precheck_instance
        self.current_menu = 'main'
        self.selected_item_index = 0
        self.editing_value = False
        self.temp_value = 0 # Temporärer Wert beim Bearbeiten
        self.current_setting_key = None # Welcher Wert gerade bearbeitet wird

        self.menus = {
            'main': {
                'title': "HAUPTMENÜ",
                'items': [
                    {"name": "1. Giesseinstellungen", "action": lambda: self.set_menu('watering_settings')},
                    {"name": "2. Ich habe umgetopft!", "action": self.repot_plant},
                    {"name": "3. Programm beenden", "action": self.exit_program}
                ]
            },
            'watering_settings': {
                'title': "GIESSEINSTELLUNGEN",
                'items': [
                    {"name": "1. Giesmenge", "key": "wateringamount", "unit": "ml", "min": 10, "max": 500, "step": 10},
                    {"name": "2. Giesintervall", "key": "wateringtimer", "unit": "Sekunden", "min": 60, "max": 86400, "step": 3600}, # 1min to 24h
                    {"name": "3. Feuchtigkeitssensor", "key": "moisturesensoruse", "type": "toggle_or_value", "min": 0, "max": 100, "step": 5},
                    {"name": "4. Zurück", "action": lambda: self.set_menu('main')}
                ]
            },
            'confirm_repot': {
                'title': "UMGETOPFT BESTÄTIGEN",
                'items': [
                    {"name": "Ja, ich habe umgetopft!", "action": self.perform_repot_action},
                    {"name": "Nein, zurück", "action": lambda: self.set_menu('main')}
                ]
            }
        }
        self.display_menu()

    def clear_console(self):
        """Löscht die Konsole für eine saubere Menüanzeige."""
        os.system('cls' if os.name == 'nt' else 'clear')

    def display_menu(self):
        """Zeigt das aktuelle Menü und die Sensorwerte an."""
        self.clear_console()
        menu = self.menus[self.current_menu]
        print(f"--- {menu['title']} ---")
        print("\n")

        # Anzeige der Sensorwerte und Status im Hauptmenü oder immer
        # Die Anzeige der Sensorwerte kann hier je nach Menü kontextabhängig gemacht werden.
        # Für Einfachheit zeigen wir sie immer an.
        self.display_sensor_status()
        print("\n")

        for i, item in enumerate(menu['items']):
            prefix = "> " if i == self.selected_item_index else "  "
            item_name = item['name']

            if "key" in item:
                current_value = current_config.get(item['key'], DEFAULT_CONFIG.get(item['key']))
                if item['key'] == "moisturesensoruse":
                    if current_value == 0:
                        item_name += f" (Aktuell: AUS)"
                    else:
                        item_name += f" (Aktuell: {current_config.get('moisturemax', DEFAULT_CONFIG['moisturemax'])}%)"
                else:
                    item_name += f" (Aktuell: {current_value} {item.get('unit', '')})"
            print(f"{prefix}{item_name}")
        print("\n--------------------")
        if self.editing_value:
            print(f"Bearbeite {self.current_setting_key}: {self.temp_value} {self.menus['watering_settings']['items'][self.selected_item_index].get('unit', '')}")
            print("Drehen zum Anpassen, Drücken zum Bestätigen.")
        else:
            print("Drehen zum Navigieren, Drücken zum Auswählen.")


    def display_sensor_status(self):
        """Zeigt die aktuellen Sensorwerte an."""
        print("--- AKTUELLE DATEN ---")
        try:
            moisture = self.ads1115.moisture_sensor_status()
            tank_ml = self.ads1115.tank_level_ml()
            tank_percent = self.ads1115.tank_level()
            print(f"Feuchtigkeit: {moisture}%")
            print(f"Tankfüllstand: {tank_ml:.2f} ml ({tank_percent}%)")

            # Berechnung wann wieder aufgefüllt werden muss (sehr grob)
            # Annahme: Wasserverbrauch pro Gießvorgang ist wateringamount
            # Wie viele Gießvorgänge sind noch möglich?
            if current_config["wateringamount"] > 0:
                remaining_waterings = tank_ml / current_config["wateringamount"]
                print(f"Verbleibende Gießvorgänge: {remaining_waterings:.1f}")
            else:
                print("Gießmenge ist 0, keine Gießvorgänge möglich.")

            # Zeit bis zum nächsten Gießen (wenn das Hauptprogramm läuft)
            # Diese Information kommt normalerweise vom Hauptprogramm, nicht von der UI
            # Hier nur ein Platzhalter
            print("Zeit bis zum nächsten Gießen: N/A (vom Hauptprogramm)")
            print("Zeit seit letztem Gießen: N/A (vom Hauptprogramm)")

        except Exception as e:
            print(f"Fehler beim Lesen der Sensordaten: {e}")
            print("Stellen Sie sicher, dass die Sensoren korrekt angeschlossen sind.")


    def navigate(self, direction):
        """Navigiert im Menü oder passt einen Wert an."""
        menu_items = self.menus[self.current_menu]['items']

        if self.editing_value:
            # Wert anpassen
            item = menu_items[self.selected_item_index]
            step = item.get("step", 1)
            min_val = item.get("min", 0)
            max_val = item.get("max", 100000) # Hoher Max-Wert als Standard

            if direction == 'right':
                self.temp_value += step
            else: # 'left'
                self.temp_value -= step

            # Wertebereich begrenzen
            self.temp_value = max(min_val, min(max_val, self.temp_value))

            # Spezialfall für Feuchtigkeitssensor: 0 (AUS) oder %-Wert
            if item['key'] == "moisturesensoruse":
                if self.temp_value < item.get("min_moisture_value", 5): # Unter einem Schwellenwert auf 0 setzen (AUS)
                    self.temp_value = 0
                elif self.temp_value > 0 and self.temp_value < item.get("min_moisture_value", 5):
                    self.temp_value = item.get("min_moisture_value", 5) # Springt auf min %-Wert wenn über 0

        else:
            # Menüpunkt auswählen
            if direction == 'right':
                self.selected_item_index = (self.selected_item_index + 1) % len(menu_items)
            else: # 'left'
                self.selected_item_index = (self.selected_item_index - 1 + len(menu_items)) % len(menu_items)
        self.display_menu()

    def confirm_selection(self):
        """Bestätigt die Auswahl im Menü oder einen Wert."""
        menu_items = self.menus[self.current_menu]['items']
        selected_item = menu_items[self.selected_item_index]

        if self.editing_value:
            # Wert bestätigen und speichern
            key = self.current_setting_key
            current_config[key] = self.temp_value

            # Spezialfall für Feuchtigkeitssensor: Wenn Wert 0 ist, ist moisturesensoruse = 0, sonst 1
            if key == "moisturesensoruse":
                if self.temp_value == 0:
                    current_config["moisturesensoruse"] = 0
                else:
                    current_config["moisturesensoruse"] = 1
                    current_config["moisturemax"] = self.temp_value # Der Wert ist dann der moisturemax

            save_config()
            self.editing_value = False
            self.current_setting_key = None
            print(f"'{selected_item['name']}' auf {current_config[key]} gespeichert.")
            time.sleep(1) # Kurze Pause, um die Nachricht zu sehen
            self.display_menu() # Menü neu anzeigen
        else:
            # Menüpunkt auswählen
            if "action" in selected_item:
                selected_item['action']()
            elif "key" in selected_item:
                # Beginne mit der Bearbeitung des Wertes
                self.editing_value = True
                self.current_setting_key = selected_item['key']
                # Initialisiere temp_value mit dem aktuellen Wert aus der Konfiguration
                if self.current_setting_key == "moisturesensoruse":
                    # Wenn moisturesensoruse 0 ist, zeige 0 an, sonst den moisturemax Wert
                    self.temp_value = current_config.get("moisturemax", DEFAULT_CONFIG["moisturemax"]) \
                        if current_config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"]) == 1 else 0
                else:
                    self.temp_value = current_config.get(self.current_setting_key, DEFAULT_CONFIG.get(self.current_setting_key))
                self.display_menu() # Menü mit Bearbeitungsmodus neu anzeigen

    def set_menu(self, menu_name):
        """Wechselt zum angegebenen Menü."""
        self.current_menu = menu_name
        self.selected_item_index = 0
        self.editing_value = False
        self.display_menu()

    def repot_plant(self):
        """Aktion für 'Ich habe umgetopft!'."""
        self.set_menu('confirm_repot') # Gehe zum Bestätigungsmenü

    def perform_repot_action(self):
        """Führt die Aktion nach dem Umtopfen aus (z.B. Pumpe einmal starten)."""
        self.clear_console()
        print("Pflanze wurde umgetopft!")
        print("Starte Pumpe für einen kurzen Testlauf (50ml)...")
        # Hier könnte man die Pumpe manuell für eine kleine Menge starten
        # oder einen "Reset" des Bewässerungszyklus im Hauptprogramm auslösen.
        # Für diesen UI-Teil starten wir die Pumpe einmalig.
        self.pump.pump_timer(50) # Starte Pumpe für 50ml
        print("Testlauf beendet.")
        time.sleep(3)
        self.set_menu('main')

    def exit_program(self):
        """Beendet das UI-Programm."""
        self.clear_console()
        print("Programm wird beendet. Auf Wiedersehen!")
        global running
        running = False


# --- Hauptprogramm-Logik ---
if __name__ == "__main__":
    # Konfiguration laden
    load_config()

    # Hardware initialisieren
    ads1115 = ADS1115()
    pump = Pump()
    prewatercheck = PreWateringCheck(ads1115)

    # Menüsystem initialisieren
    menu_system = MenuSystem(ads1115, pump, prewatercheck)

    # Drehgeber initialisieren und MenuSystem-Referenz übergeben
    encoder = RotaryEncoder(menu_system)

    # Drehgeber-Threads starten
    encoder.start_thread()

    running = True
    try:
        while running:
            # Das Hauptprogramm läuft in einer Schleife, um die UI aktiv zu halten
            # und auf Drehgeber-Eingaben zu warten (die über Callbacks verarbeitet werden).
            time.sleep(0.1) # Kurze Pause, um CPU-Auslastung zu reduzieren

    except KeyboardInterrupt:
        print("\nProgramm durch Benutzer beendet (Ctrl+C).")
    except Exception as e:
        print(f"\nEin unerwarteter Fehler ist aufgetreten: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # GPIO-Pins aufräumen und Drehgeber-Threads stoppen
        if 'encoder' in locals() and encoder:
            encoder.stop_thread()
        GPIO.cleanup()
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")

