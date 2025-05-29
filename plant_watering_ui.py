import tkinter as tk
from tkinter import messagebox, simpledialog
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
    messagebox.showerror("Import Error", "Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.\n"
                                         "Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
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

# --- GUI-Anwendungsklasse ---
class PlantWateringApp(tk.Tk):
    def __init__(self, ads_instance, pump_instance, precheck_instance):
        super().__init__()
        self.title("Pflanzenbewässerungssystem")
        self.geometry("800x480") # Standardgröße für Raspberry Pi Touchscreen
        # self.attributes('-fullscreen', True) # Für Vollbild auf Touchscreen

        self.ads1115 = ads_instance
        self.pump = pump_instance
        self.precheck = precheck_instance

        self.current_frame = None
        self.frames = {} # Dictionary zum Speichern der Frames

        # Konfiguriere das Grid für das Hauptfenster
        self.grid_rowconfigure(0, weight=1) # Zeile für die Haupt-Content-Frames
        self.grid_rowconfigure(1, weight=0) # Zeile für den Sensorstatus (feste Höhe)
        self.grid_columnconfigure(0, weight=1)

        self.create_frames()
        self.create_sensor_status_display() # Neue Methode für Sensor-Labels
        self.show_frame("main_menu")

        self.update_sensor_data() # Sensorwerte initial aktualisieren und Timer starten

    def create_frames(self):
        """Erstellt alle Haupt-Frames für die Menüansichten."""
        # Hauptmenü-Frame
        self.frames["main_menu"] = MainMenuFrame(self, self)
        self.frames["main_menu"].grid(row=0, column=0, sticky="nsew")

        # Giesseinstellungen-Frame
        self.frames["watering_settings"] = WateringSettingsFrame(self, self)
        self.frames["watering_settings"].grid(row=0, column=0, sticky="nsew")

        # Umtopfen-Bestätigungs-Frame
        self.frames["confirm_repot"] = ConfirmRepotFrame(self, self)
        self.frames["confirm_repot"].grid(row=0, column=0, sticky="nsew")

        # Die grid_rowconfigure und grid_columnconfigure für das Hauptfenster
        # wurden in __init__ verschoben, um den Fehler zu beheben.

    def create_sensor_status_display(self):
        """Erstellt und platziert den Frame für die Sensorstatusanzeige."""
        self.sensor_status_frame = tk.Frame(self, bg="#34495e", bd=2, relief="groove")
        # Platziere den Sensorstatus-Frame in der zweiten Reihe (Index 1) des Grids
        self.sensor_status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        # Labels für Sensorstatus - packe sie innerhalb des neuen Frames
        self.moisture_label = tk.Label(self.sensor_status_frame, text="Feuchtigkeit: --%", font=("Inter", 14), fg="white", bg="#34495e")
        self.moisture_label.pack(side="left", padx=10, pady=2)
        self.tank_label = tk.Label(self.sensor_status_frame, text="Tankfüllstand: -- ml (--%)", font=("Inter", 14), fg="white", bg="#34495e")
        self.tank_label.pack(side="left", padx=10, pady=2)
        self.remaining_waterings_label = tk.Label(self.sensor_status_frame, text="Verbleibende Gießvorgänge: --", font=("Inter", 14), fg="white", bg="#34495e")
        self.remaining_waterings_label.pack(side="left", padx=10, pady=2)

        # Konfiguriere die Spalten im sensor_status_frame, damit sie sich gleichmäßig ausdehnen
        self.sensor_status_frame.grid_columnconfigure(0, weight=1)
        self.sensor_status_frame.grid_columnconfigure(1, weight=1)
        self.sensor_status_frame.grid_columnconfigure(2, weight=1)


    def show_frame(self, frame_name):
        """Zeigt den angegebenen Frame an und verbirgt alle anderen."""
        frame = self.frames[frame_name]
        frame.tkraise()
        self.current_frame = frame
        # Wenn wir zu einem Einstellungs-Frame wechseln, aktualisiere die Werte
        if frame_name == "watering_settings":
            frame.update_display_values()

    def update_sensor_data(self):
        """Aktualisiert die Anzeige der Sensorwerte."""
        try:
            moisture = self.ads1115.moisture_sensor_status()
            tank_ml = self.ads1115.tank_level_ml()
            tank_percent = self.ads1115.tank_level()

            self.moisture_label.config(text=f"Feuchtigkeit: {moisture}%")
            self.tank_label.config(text=f"Tankfüllstand: {tank_ml:.2f} ml ({tank_percent}%)")

            if current_config["wateringamount"] > 0:
                remaining_waterings = tank_ml / current_config["wateringamount"]
                self.remaining_waterings_label.config(text=f"Verbleibende Gießvorgänge: {remaining_waterings:.1f}")
            else:
                self.remaining_waterings_label.config(text="Gießmenge ist 0, keine Gießvorgänge möglich.")

        except Exception as e:
            print(f"Fehler beim Lesen der Sensordaten: {e}")
            self.moisture_label.config(text="Feuchtigkeit: Fehler")
            self.tank_label.config(text="Tankfüllstand: Fehler")
            self.remaining_waterings_label.config(text="Gießvorgänge: Fehler")

        # Aktualisiere alle 5 Sekunden
        self.after(5000, self.update_sensor_data)

    def repot_plant_action(self):
        """Führt die Aktion nach dem Umtopfen aus (z.B. Pumpe einmal starten)."""
        messagebox.showinfo("Umgetopft", "Pflanze wurde umgetopft!\nStarte Pumpe für einen kurzen Testlauf (50ml)...")
        # Starte Pumpe in einem separaten Thread, um die GUI nicht zu blockieren
        threading.Thread(target=self._run_repot_pump_test, daemon=True).start()
        self.show_frame("main_menu")

    def _run_repot_pump_test(self):
        """Interner Thread für den Pumpentest nach dem Umtopfen."""
        try:
            self.pump.pump_timer(50) # Starte Pumpe für 50ml
            messagebox.showinfo("Umgetopft", "Testlauf beendet.")
        except Exception as e:
            messagebox.showerror("Pumpenfehler", f"Fehler beim Pumpentest: {e}")

    def exit_program(self):
        """Beendet das GUI-Programm."""
        if messagebox.askyesno("Beenden", "Möchten Sie das Programm wirklich beenden?"):
            self.destroy() # Schließt das Tkinter-Fenster

# --- Frame-Klassen für die Menüs ---
class BaseMenuFrame(tk.Frame):
    """Basisklasse für Menü-Frames."""
    def __init__(self, parent, controller):
        super().__init__(parent, bg="#2c3e50") # Dunkler Hintergrund
        self.controller = controller
        self.create_widgets()

    def create_widgets(self):
        """Muss von Unterklassen implementiert werden."""
        raise NotImplementedError

class MainMenuFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="HAUPTMENÜ", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)

        button_style = {"font": ("Inter", 18), "bg": "#3498db", "fg": "white", "padx": 20, "pady": 10, "relief": "raised", "bd": 3, "width": 25}

        tk.Button(self, text="1. Giesseinstellungen", command=lambda: self.controller.show_frame("watering_settings"), **button_style).pack(pady=10)
        tk.Button(self, text="2. Ich habe umgetopft!", command=lambda: self.controller.show_frame("confirm_repot"), **button_style).pack(pady=10)
        tk.Button(self, text="3. Programm beenden", command=self.controller.exit_program, **button_style).pack(pady=10)

class WateringSettingsFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="GIESSEINSTELLUNGEN", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)

        self.setting_vars = {} # Speichert StringVar/IntVar für die Anzeige der Werte
        self.value_entries = {} # Speichert Entry/Spinbox Widgets
        self.current_editor_frame = None # Frame für die Wertbearbeitung

        # Die settings_data als Instanzvariable speichern, damit sie in get_unit_for_key zugänglich ist
        self.settings_data = [
            {"label": "1. Gießmenge:", "key": "wateringamount", "unit": "ml", "min": 10, "max": 500, "step": 10},
            {"label": "2. Gießintervall:", "key": "wateringtimer", "unit": "Sekunden", "min": 60, "max": 86400, "step": 3600},
            {"label": "3. Feuchtigkeitssensor:", "key": "moisturesensoruse", "type": "toggle_and_value", "min_moisture": 5, "max_moisture": 100, "step_moisture": 5},
        ]

        for i, setting in enumerate(self.settings_data): # Hier self.settings_data verwenden
            frame = tk.Frame(self, bg="#2c3e50")
            frame.pack(pady=5, fill="x", padx=50)

            label = tk.Label(frame, text=setting["label"], font=("Inter", 16), fg="white", bg="#2c3e50", anchor="w")
            label.pack(side="left", padx=10, fill="x", expand=True)

            var = tk.StringVar(self)
            self.setting_vars[setting["key"]] = var
            value_label = tk.Label(frame, textvariable=var, font=("Inter", 16, "bold"), fg="#2ecc71", bg="#2c3e50", width=15, anchor="e")
            value_label.pack(side="left", padx=10)

            edit_button = tk.Button(frame, text="Bearbeiten", font=("Inter", 14), bg="#f39c12", fg="white",
                                    command=lambda s=setting: self.open_editor(s))
            edit_button.pack(side="right", padx=10)

        tk.Button(self, text="Zurück zum Hauptmenü", font=("Inter", 18), bg="#e74c3c", fg="white",
                  command=lambda: self.controller.show_frame("main_menu"), padx=20, pady=10, relief="raised", bd=3, width=25).pack(pady=20)

        self.update_display_values()

    def update_display_values(self):
        """Aktualisiert die angezeigten Werte der Einstellungen."""
        for key, var in self.setting_vars.items():
            if key == "moisturesensoruse":
                if current_config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"]) == 0:
                    var.set("AUS")
                else:
                    var.set(f"{current_config.get('moisturemax', DEFAULT_CONFIG['moisturemax'])}%")
            else:
                var.set(f"{current_config.get(key, DEFAULT_CONFIG.get(key))} {self.get_unit_for_key(key)}")

    def get_unit_for_key(self, key):
        """Hilfsfunktion, um die Einheit für einen Schlüssel zu finden."""
        # Direkt aus der settings_data Liste des Frames abrufen
        for setting in self.settings_data:
            if setting["key"] == key:
                return setting.get("unit", "")
        return "" # Standard

    def open_editor(self, setting):
        """Öffnet einen Editor für die ausgewählte Einstellung."""
        if self.current_editor_frame:
            self.current_editor_frame.destroy()

        self.current_editor_frame = SettingEditorFrame(self, self.controller, setting, self.update_display_values)
        self.current_editor_frame.pack(fill="both", expand=True, pady=10)


class SettingEditorFrame(tk.Frame):
    """Frame zum Bearbeiten einzelner Einstellungen."""
    def __init__(self, parent_frame, controller, setting_data, update_callback):
        super().__init__(parent_frame, bg="#34495e", bd=5, relief="groove")
        self.controller = controller
        self.setting_data = setting_data
        self.update_callback = update_callback
        self.temp_value = tk.IntVar(self) # Temporärer Wert für die Bearbeitung

        self.create_editor_widgets()

    def create_editor_widgets(self):
        tk.Label(self, text=f"Bearbeite: {self.setting_data['label'].replace(':', '')}", font=("Inter", 20, "bold"), fg="white", bg="#34495e").pack(pady=10)

        # Initialisiere temp_value mit dem aktuellen Wert
        if self.setting_data['key'] == "moisturesensoruse":
            # Wenn moisturesensoruse 0 ist, zeige 0 an, sonst den moisturemax Wert
            initial_val = current_config.get("moisturemax", DEFAULT_CONFIG["moisturemax"]) \
                if current_config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"]) == 1 else 0
            self.temp_value.set(initial_val)
        else:
            self.temp_value.set(current_config.get(self.setting_data['key'], DEFAULT_CONFIG.get(self.setting_data['key'])))

        # Widget zur Wertanpassung
        if self.setting_data['key'] == "moisturesensoruse":
            # Toggle-Button für AN/AUS und Spinbox für %-Wert
            self.toggle_var = tk.IntVar(self)
            self.toggle_var.set(current_config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"]))

            toggle_frame = tk.Frame(self, bg="#34495e")
            toggle_frame.pack(pady=10)

            tk.Checkbutton(toggle_frame, text="Sensor verwenden", variable=self.toggle_var,
                           font=("Inter", 16), fg="white", bg="#34495e", selectcolor="#2c3e50",
                           command=self.on_toggle_sensor_use).pack(side="left", padx=10)

            self.moisture_spinbox = tk.Spinbox(toggle_frame, from_=self.setting_data.get("min_moisture", 0),
                                               to=self.setting_data.get("max_moisture", 100),
                                               increment=self.setting_data.get("step_moisture", 5),
                                               textvariable=self.temp_value, font=("Inter", 16), width=5,
                                               state="normal" if self.toggle_var.get() == 1 else "disabled")
            self.moisture_spinbox.pack(side="left", padx=10)
            tk.Label(toggle_frame, text="%", font=("Inter", 16), fg="white", bg="#34495e").pack(side="left")

            # Setze den Wert der Spinbox auf den aktuellen moisturemax, wenn der Sensor aktiv ist
            if self.toggle_var.get() == 1:
                self.temp_value.set(current_config.get("moisturemax", DEFAULT_CONFIG["moisturemax"]))
            else:
                self.temp_value.set(0) # Wenn Sensor aus, zeige 0 an


        else:
            # Für numerische Werte: +/- Buttons und Anzeige
            value_frame = tk.Frame(self, bg="#34495e")
            value_frame.pack(pady=10)

            tk.Button(value_frame, text="<", font=("Inter", 20, "bold"), bg="#e67e22", fg="white",
                      command=lambda: self.adjust_value(-self.setting_data.get("step", 1)), width=5, height=2).pack(side="left", padx=10)

            tk.Label(value_frame, textvariable=self.temp_value, font=("Inter", 24, "bold"), fg="#ecf0f1", bg="#34495e", width=8).pack(side="left", padx=10)
            tk.Label(value_frame, text=self.setting_data.get("unit", ""), font=("Inter", 20), fg="white", bg="#34495e").pack(side="left")

            tk.Button(value_frame, text=">", font=("Inter", 20, "bold"), bg="#27ae60", fg="white",
                      command=lambda: self.adjust_value(self.setting_data.get("step", 1)), width=5, height=2).pack(side="left", padx=10)

        tk.Button(self, text="Bestätigen", font=("Inter", 18), bg="#2980b9", fg="white",
                  command=self.save_and_close, padx=20, pady=10, relief="raised", bd=3, width=20).pack(pady=20)
        tk.Button(self, text="Abbrechen", font=("Inter", 18), bg="#c0392b", fg="white",
                  command=self.cancel_and_close, padx=20, pady=10, relief="raised", bd=3, width=20).pack(pady=10)

    def on_toggle_sensor_use(self):
        """Behandelt das Umschalten des Feuchtigkeitssensors."""
        if self.toggle_var.get() == 1: # Sensor ist AN
            self.moisture_spinbox.config(state="normal")
            # Setze den Wert auf den aktuellen moisturemax, wenn er 0 war
            if self.temp_value.get() == 0:
                self.temp_value.set(current_config.get("moisturemax", DEFAULT_CONFIG["moisturemax"]))
        else: # Sensor ist AUS
            self.moisture_spinbox.config(state="disabled")
            self.temp_value.set(0) # Setze den temporären Wert auf 0

    def adjust_value(self, change):
        """Passt den Wert der Einstellung an."""
        new_val = self.temp_value.get() + change
        min_val = self.setting_data.get("min", 0)
        max_val = self.setting_data.get("max", 100000)

        # Wertebereich begrenzen
        new_val = max(min_val, min(max_val, new_val))
        self.temp_value.set(new_val)

    def save_and_close(self):
        """Speichert den bearbeiteten Wert und schließt den Editor."""
        key = self.setting_data['key']

        if key == "moisturesensoruse":
            current_config["moisturesensoruse"] = self.toggle_var.get()
            if self.toggle_var.get() == 1: # Wenn Sensor aktiv, speichere den %-Wert als moisturemax
                current_config["moisturemax"] = self.temp_value.get()
        else:
            current_config[key] = self.temp_value.get()

        save_config()
        messagebox.showinfo("Gespeichert", f"'{self.setting_data['label'].replace(':', '')}' auf {self.temp_value.get()} {self.setting_data.get('unit', '')} gespeichert.")
        self.update_callback() # Aktualisiere die Anzeige im WateringSettingsFrame
        self.destroy() # Schließe den Editor-Frame

    def cancel_and_close(self):
        """Schließt den Editor ohne zu speichern."""
        self.destroy() # Schließe den Editor-Frame

class ConfirmRepotFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="PFLANZE UMGETOPFT?", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=40)
        tk.Label(self, text="Möchten Sie bestätigen, dass die Pflanze umgetopft wurde?", font=("Inter", 18), fg="white", bg="#2c3e50").pack(pady=20)

        button_style = {"font": ("Inter", 18), "padx": 20, "pady": 10, "relief": "raised", "bd": 3, "width": 15}

        tk.Button(self, text="Ja", command=self.controller.repot_plant_action, bg="#27ae60", fg="white", **button_style).pack(pady=10)
        tk.Button(self, text="Nein (Zurück)", command=lambda: self.controller.show_frame("main_menu"), bg="#e74c3c", fg="white", **button_style).pack(pady=10)


# --- Hauptprogramm-Logik ---
if __name__ == "__main__":
    # Konfiguration laden
    load_config()

    # Hardware initialisieren
    # Dies sollte nur einmal am Anfang des GUI-Programms geschehen
    ads1115 = ADS1115()
    pump = Pump()
    prewatercheck = PreWateringCheck(ads1115)

    # GUI-Anwendung starten
    app = PlantWateringApp(ads1115, pump, prewatercheck)

    # Der Drehgeber wird in dieser GUI-Version nicht direkt für die Navigation verwendet,
    # da die Bedienung über Maus/Touchscreen erfolgt.
    # Wenn du den Drehgeber zusätzlich zur GUI verwenden möchtest,
    # müsstest du seine Callbacks an die GUI-Methoden anpassen.
    # encoder = RotaryEncoder(app) # Hier würde man die App-Instanz übergeben
    # encoder.start_thread() # Und hier starten

    try:
        app.mainloop() # Startet die Tkinter-Event-Schleife
    except Exception as e:
        print(f"\nEin Fehler ist während der Ausführung aufgetreten: {e}")
        import traceback
        traceback.print_exc() # Vollständigen Traceback für Debugging ausgeben
    finally:
        # Hier könnten noch Aufräumarbeiten für den Drehgeber erfolgen, falls er verwendet wird
        # if 'encoder' in locals() and encoder:
        #     encoder.stop_thread()
        GPIO.cleanup()
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")
