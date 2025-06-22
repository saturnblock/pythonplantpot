import tkinter as tk
from tkinter import messagebox, simpledialog
import json
import time
import threading
import os
import sys
from datetime import datetime, timedelta
import RPi.GPIO as GPIO # Hinzugefügt für GPIO.cleanup() im finally-Block

# Importiere die Hardware-Utilities
try:
    from pi_hardware_utils import ADS1115, RotaryEncoder, Pump, PreWateringCheck, TANK_VOLUME
except ImportError:
    messagebox.showerror("Import Error", "Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.\n"
                                         "Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
    sys.exit(1)

# --- Globale Konfiguration und Statusdateien ---
CONFIG_FILE = 'config.json'
PUMP_COMMAND_FILE = 'pump_command.json'
WATERING_STATUS_FILE = 'watering_status.json' # Neue Statusdatei

# Standardwerte für die Pflanzenbewässerung
DEFAULT_CONFIG = {
    "wateringtimer": 60,  # in s (1 Stunde)
    "wateringamount": 20,   # in ml
    "moisturemax": 50,      # in % (wenn Feuchtigkeit darunter, wird gegossen)
    "moisturesensoruse": 1  # 1 für aktiv, 0 für inaktiv
}

current_config = {} # Wird beim Start aus config.json geladen

# Globaler Status für die Bewässerung (aus watering_status.json geladen)
watering_status_gui = {
    "last_watering_time": None,
    "estimated_next_watering_time": None,
    "remaining_watering_cycles": 0,
    "current_timer_remaining_s": 0
}

# --- Funktionen zum Laden/Speichern der Konfiguration und des Status ---
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

def load_watering_status_gui():
    """Lädt den Bewässerungsstatus aus der watering_status.json-Datei für die GUI."""
    global watering_status_gui
    try:
        with open(WATERING_STATUS_FILE, 'r') as f:
            data = json.load(f)
            for key in watering_status_gui:
                if key in data:
                    watering_status_gui[key] = data[key]
            # print("GUI: Bewässerungsstatus erfolgreich geladen.") # Auskommentiert für weniger Konsolenausgabe
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        # print("GUI: Bewässerungsstatusdatei nicht gefunden oder beschädigt. Verwende Standardwerte.")
        # Dies ist normal, wenn das Hauptprogramm noch nicht gelaufen ist oder die Datei noch nicht erstellt hat.
        pass
    except Exception as e:
        print(f"GUI: Unerwarteter Fehler beim Laden des Bewässerungsstatus: {e}")


def send_pump_command(amount_ml=None, action="pump_manual"):
    """Sendet einen Befehl an das Hauptsystem, die Pumpe zu starten oder einen Reset durchzuführen."""
    try:
        command_data = {"action": action}
        if amount_ml is not None:
            command_data["amount_ml"] = amount_ml

        with open(PUMP_COMMAND_FILE, 'w') as f:
            json.dump(command_data, f)
        print(f"Pumpenbefehl '{action}' mit Menge '{amount_ml}' an '{PUMP_COMMAND_FILE}' gesendet.")

        # Warte, bis der Befehl verarbeitet wurde (Datei wird zurückgesetzt)
        max_wait_time = 10 # Sekunden
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            try:
                with open(PUMP_COMMAND_FILE, 'r') as f:
                    command = json.load(f)
                if command.get("action") == "none":
                    print("Pumpenbefehl vom Hauptsystem verarbeitet.")
                    return True
            except (FileNotFoundError, json.JSONDecodeError):
                pass # Datei könnte gerade geschrieben werden oder noch nicht existieren
            time.sleep(0.1) # Kurze Wartezeit vor dem nächsten Check
        print("Timeout: Pumpenbefehl wurde möglicherweise nicht verarbeitet.")
        return False
    except Exception as e:
        print(f"Fehler beim Senden des Pumpenbefehls: {e}")
        return False


# --- GUI-Anwendungsklasse ---
class PlantWateringApp(tk.Tk):
    IDLE_TIMEOUT_MS = 60000

    def __init__(self, ads_instance, precheck_instance):
        super().__init__()
        self.title("Pflanzenbewässerungssystem")
        self.geometry("800x480") # Standardgröße für Raspberry Pi Touchscreen
        # self.attributes('-fullscreen', True) # Für Vollbild auf Touchscreen

        self.ads1115 = ads_instance
        self.precheck = precheck_instance

        self.current_frame = None
        self.frames = {} # Dictionary zum Speichern der Frames

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self.create_frames()
        self.create_sensor_status_display()
        self.show_frame("main_menu")

        self.update_sensor_data() # Sensorwerte initial aktualisieren und Timer starten

        # Idle-Timer-Logik
        self.idle_timer_id = None
        self.bind_all('<Any-Key>', self.reset_idle_timer)
        self.bind_all('<Button-1>', self.reset_idle_timer)
        self.reset_idle_timer()

    def create_frames(self):
        self.frames["main_menu"] = MainMenuFrame(self, self)
        self.frames["main_menu"].grid(row=0, column=0, sticky="nsew")

        self.frames["watering_settings"] = WateringSettingsFrame(self, self)
        self.frames["watering_settings"].grid(row=0, column=0, sticky="nsew")

        # NEU: Frame für manuelle Bewässerung
        self.frames["manual_watering"] = ManualWateringFrame(self, self)
        self.frames["manual_watering"].grid(row=0, column=0, sticky="nsew")

        self.frames["confirm_repot"] = ConfirmRepotFrame(self, self)
        self.frames["confirm_repot"].grid(row=0, column=0, sticky="nsew")

        self.frames["idle_screen"] = IdleScreenFrame(self, self)
        self.frames["idle_screen"].grid(row=0, column=0, sticky="nsew")


    def create_sensor_status_display(self):
        """Erstellt und platziert den Frame für die Sensorstatusanzeige."""
        self.sensor_status_frame = tk.Frame(self, bg="#34495e", bd=2, relief="groove")
        # Platziere den Sensorstatus-Frame in der zweiten Reihe (Index 1) des Grids
        self.sensor_status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        # Labels für Sensorstatus - platziere sie innerhalb des neuen Frames mit grid
        # Jedes Label bekommt eine eigene Spalte und dehnt sich gleichmäßig aus
        self.moisture_label = tk.Label(self.sensor_status_frame, text="Feuchtigkeit: --%", font=("Inter", 14), fg="white", bg="#34495e")
        self.moisture_label.grid(row=0, column=0, padx=2, pady=2, sticky="ew") # Reduziere padx weiter

        self.tank_label = tk.Label(self.sensor_status_frame, text="Tankfüllstand: -- ml (--%)", font=("Inter", 14), fg="white", bg="#34495e")
        self.tank_label.grid(row=0, column=1, padx=2, pady=2, sticky="ew") # Reduziere padx weiter

        self.remaining_waterings_label = tk.Label(self.sensor_status_frame, text="Verbleibende Gießvorgänge: --", font=("Inter", 14), fg="white", bg="#34495e")
        self.remaining_waterings_label.grid(row=0, column=2, padx=2, pady=2, sticky="ew") # Reduziere padx weiter

        # Konfiguriere die Spalten im sensor_status_frame, damit sie sich gleichmäßig ausdehnen
        self.sensor_status_frame.grid_columnconfigure(0, weight=1)
        self.sensor_status_frame.grid_columnconfigure(1, weight=1)
        self.sensor_status_frame.grid_columnconfigure(2, weight=1)


    def show_frame(self, frame_name):
        frame = self.frames[frame_name]
        frame.tkraise()
        self.current_frame = frame

        if frame_name == "watering_settings":
            frame.update_display_values()
        elif frame_name == "idle_screen":
            frame.update_idle_data()

    def update_sensor_data(self):
        """Aktualisiert die Anzeige der Sensorwerte und den Bewässerungsstatus."""
        load_watering_status_gui() # Lade den neuesten Status von der Datei

        try:
            moisture = self.ads1115.moisture_sensor_status()
            tank_ml = self.ads1115.tank_level_ml()
            tank_percent = self.ads1115.tank_level()

            self.moisture_label.config(text=f"Feuchtigkeit: {moisture}%")
            self.tank_label.config(text=f"Tankfüllstand: {tank_ml:.2f} ml ({tank_percent}%)")

            # Zeige die verbleibenden Gießvorgänge aus dem Status an
            self.remaining_waterings_label.config(text=f"Verbleibende Gießvorgänge: {watering_status_gui['remaining_watering_cycles']}")

            # Wenn der aktuelle Frame der Idle-Screen ist, aktualisiere auch dessen Daten
            if self.current_frame == self.frames["idle_screen"]:
                self.frames["idle_screen"].update_idle_data()

        except Exception as e:
            print(f"Fehler beim Lesen der Sensordaten: {e}")
            self.moisture_label.config(text="Feuchtigkeit: Fehler")
            self.tank_label.config(text="Tankfüllstand: Fehler")
            self.remaining_waterings_label.config(text="Gießvorgänge: Fehler")

        self.after(1000, self.update_sensor_data) # Aktualisiere jede Sekunde, um den Idle-Screen flüssig zu halten

    def repot_plant_action(self):
        """Sendet den Umtopf-Reset-Befehl an das Hauptsystem."""
        messagebox.showinfo("Umgetopft", "Pflanze wurde umgetopft!\nSende Befehl zum Zurücksetzen des Gießzyklus...")
        # Sende Befehl zum Zurücksetzen des Gießstatus an das Hauptsystem
        threading.Thread(target=self._send_repot_reset_command, daemon=True).start()
        self.show_frame("main_menu")

    def _send_repot_reset_command(self):
        """Interner Thread zum Senden des Umtopf-Reset-Befehls."""
        if send_pump_command(action="repot_reset"): # Sende den Reset-Befehl
            messagebox.showinfo("Umgetopft", "Gießzyklus-Reset-Befehl gesendet und verarbeitet.")
        else:
            messagebox.showerror("Fehler", "Fehler beim Senden oder Verarbeiten des Umtopf-Reset-Befehls.")

    # NEU: Logik zur Auslösung der manuellen Bewässerung
    def trigger_manual_watering(self, amount_ml=None):
        """Löst die manuelle Bewässerung aus, fragt ggf. nach der Menge."""
        water_amount = 0
        if amount_ml is None:
            # Frage nach einer benutzerdefinierten Menge
            custom_amount = simpledialog.askinteger("Manuelle Bewässerung",
                                                    "Wie viele ml sollen gegossen werden?",
                                                    parent=self,
                                                    minvalue=10,
                                                    maxvalue=500)
            if custom_amount is not None:
                water_amount = custom_amount
            else:
                return # Benutzer hat abgebrochen
        else:
            # Verwende die Standardmenge
            water_amount = amount_ml

        if water_amount > 0:
            # Zeige eine Informationsmeldung, bevor der Thread startet
            messagebox.showinfo("Befehl wird gesendet", f"Sende Befehl, {water_amount} ml zu gießen...", parent=self)
            # Starte den Befehl in einem separaten Thread, um die GUI nicht zu blockieren
            threading.Thread(target=self._send_manual_pump_command, args=(water_amount,), daemon=True).start()

    # NEU: Thread-Funktion zum Senden des manuellen Pumpenbefehls
    def _send_manual_pump_command(self, amount_ml):
        """Interner Thread zum Senden des manuellen Pumpenbefehls."""
        if send_pump_command(amount_ml=amount_ml, action="pump_manual"):
            # Diese Messagebox erscheint, nachdem der Befehl vom System verarbeitet wurde
            messagebox.showinfo("Erfolg", f"{amount_ml} ml wurden gegossen.", parent=self)
        else:
            # Diese Messagebox erscheint bei einem Timeout oder Fehler
            messagebox.showerror("Fehler", "Pumpenbefehl konnte nicht verarbeitet werden (Timeout).", parent=self)


    def exit_program(self):
        """Beendet das GUI-Programm."""
        if messagebox.askyesno("Beenden", "Möchten Sie das Programm wirklich beenden?"):
            self.destroy()

    def reset_idle_timer(self, event=None):
        """Setzt den Idle-Timer zurück und wechselt ggf. zum Hauptmenü."""
        if self.idle_timer_id:
            self.after_cancel(self.idle_timer_id)

        if self.current_frame == self.frames["idle_screen"] and event is not None:
            self.show_frame("main_menu")

        self.idle_timer_id = self.after(self.IDLE_TIMEOUT_MS, self.go_to_idle_screen)

    def go_to_idle_screen(self):
        """Wechselt zum Idle-Screen."""
        self.show_frame("idle_screen")


# --- Frame-Klassen für die Menüs ---
class BaseMenuFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg="#2c3e50")
        self.controller = controller
        self.create_widgets()

class MainMenuFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="HAUPTMENÜ", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)

        button_style = {"font": ("Inter", 18), "bg": "#3498db", "fg": "white", "padx": 20, "pady": 10, "relief": "raised", "bd": 3, "width": 25}

        tk.Button(self, text="1. Giesseinstellungen", command=lambda: self.controller.show_frame("watering_settings"), **button_style).pack(pady=10)
        # NEU: Button für manuelle Bewässerung
        tk.Button(self, text="2. Manuelle Bewässerung", command=lambda: self.controller.show_frame("manual_watering"), **button_style).pack(pady=10)
        tk.Button(self, text="3. Ich habe umgetopft!", command=lambda: self.controller.show_frame("confirm_repot"), **button_style).pack(pady=10)
        tk.Button(self, text="4. Programm beenden", command=self.controller.exit_program, **button_style).pack(pady=10)
        tk.Button(self, text="5. Zum Idle-Screen", command=lambda: self.controller.show_frame("idle_screen"), **button_style).pack(pady=10)


class WateringSettingsFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="GIESSEINSTELLUNGEN", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)

        self.setting_vars = {}
        self.settings_data = [
            {"label": "1. Gießmenge:", "key": "wateringamount", "unit": "ml", "min": 10, "max": 500, "step": 10},
            {"label": "2. Gießintervall:", "key": "wateringtimer", "type": "time_duration", "unit": "s", "min": 60, "max": 86400, "step": 3600}, # Typ hinzugefügt
            {"label": "3. Feuchtigkeitssensor:", "key": "moisturesensoruse", "type": "toggle_and_value", "min_moisture": 5, "max_moisture": 100, "step_moisture": 5},
        ]

        for i, setting in enumerate(self.settings_data):
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
        for key, var in self.setting_vars.items():
            if key == "moisturesensoruse":
                if current_config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"]) == 0:
                    var.set("AUS")
                else:
                    var.set(f"{current_config.get('moisturemax', DEFAULT_CONFIG['moisturemax'])}%")
            elif key == "wateringtimer":
                total_seconds = current_config.get(key, DEFAULT_CONFIG.get(key))
                days, remainder = divmod(total_seconds, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                var.set(f"{int(days)}T {int(hours)}h {int(minutes)}m")
            else:
                var.set(f"{current_config.get(key, DEFAULT_CONFIG.get(key))} {self.get_unit_for_key(key)}")

    def get_unit_for_key(self, key):
        for setting in self.settings_data:
            if setting["key"] == key:
                return setting.get("unit", "")
        return ""

    def open_editor(self, setting):
        editor_window = SettingEditorFrame(self.controller, setting, self.update_display_values)
        self.controller.update_idletasks()
        x = self.controller.winfo_x() + (self.controller.winfo_width() // 2) - (editor_window.winfo_width() // 2)
        y = self.controller.winfo_y() + (self.controller.winfo_height() // 2) - (editor_window.winfo_height() // 2)
        editor_window.geometry(f"+{x}+{y}")
        editor_window.grab_set()
        self.controller.wait_window(editor_window)


class SettingEditorFrame(tk.Toplevel):
    def __init__(self, controller, setting_data, update_callback):
        super().__init__(controller)
        self.title(f"Bearbeite: {setting_data['label'].replace(':', '')}")
        self.transient(controller)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel_and_close)

        self.controller = controller
        self.setting_data = setting_data
        self.update_callback = update_callback

        self.configure(bg="#34495e", bd=5, relief="groove")
        self.create_editor_widgets()

    def create_editor_widgets(self):
        tk.Label(self, text=f"Bearbeite: {self.setting_data['label'].replace(':', '')}", font=("Inter", 20, "bold"), fg="white", bg="#34495e").pack(pady=10)

        if self.setting_data['key'] == "moisturesensoruse":
            self.toggle_var = tk.IntVar(self)
            self.toggle_var.set(current_config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"]))
            self.temp_value = tk.IntVar(self) # Für den %-Wert

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

            if self.toggle_var.get() == 1:
                self.temp_value.set(current_config.get("moisturemax", DEFAULT_CONFIG["moisturemax"]))
            else:
                self.temp_value.set(0)

        elif self.setting_data['type'] == "time_duration":
            # Gießintervall in Tagen, Stunden, Minuten
            total_seconds = current_config.get(self.setting_data['key'], DEFAULT_CONFIG.get(self.setting_data['key']))
            days, remainder = divmod(total_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60) # Sekunden werden nicht direkt angezeigt, aber für die Umrechnung benötigt

            self.days_var = tk.IntVar(self, value=int(days))
            self.hours_var = tk.IntVar(self, value=int(hours))
            self.minutes_var = tk.IntVar(self, value=int(minutes))

            # Trace-Variablen, um Änderungen zu erkennen und die Gesamtzeit zu aktualisieren
            self.days_var.trace_add("write", self._update_total_seconds_from_fields)
            self.hours_var.trace_add("write", self._update_total_seconds_from_fields)
            self.minutes_var.trace_add("write", self._update_total_seconds_from_fields)

            time_frame = tk.Frame(self, bg="#34495e")
            time_frame.pack(pady=10)

            # Tage
            tk.Label(time_frame, text="Tage:", font=("Inter", 16), fg="white", bg="#34495e").grid(row=0, column=0, padx=5, pady=2)
            tk.Spinbox(time_frame, from_=0, to=365, textvariable=self.days_var, font=("Inter", 16), width=5).grid(row=0, column=1, padx=5, pady=2)

            # Stunden
            tk.Label(time_frame, text="Stunden:", font=("Inter", 16), fg="white", bg="#34495e").grid(row=1, column=0, padx=5, pady=2)
            tk.Spinbox(time_frame, from_=0, to=23, textvariable=self.hours_var, font=("Inter", 16), width=5).grid(row=1, column=1, padx=5, pady=2)

            # Minuten
            tk.Label(time_frame, text="Minuten:", font=("Inter", 16), fg="white", bg="#34495e").grid(row=2, column=0, padx=5, pady=2)
            tk.Spinbox(time_frame, from_=0, to=59, textvariable=self.minutes_var, font=("Inter", 16), width=5).grid(row=2, column=1, padx=5, pady=2)

            self.total_seconds_label = tk.Label(time_frame, text=f"Gesamt: {total_seconds}s", font=("Inter", 14), fg="#95a5a6", bg="#34495e")
            self.total_seconds_label.grid(row=3, columnspan=2, pady=5)
            self.temp_value = tk.IntVar(self, value=total_seconds) # Speichert den Gesamtsekundenwert

        else:
            # Für numerische Werte: +/- Buttons und Anzeige
            self.temp_value = tk.IntVar(self, value=current_config.get(self.setting_data['key'], DEFAULT_CONFIG.get(self.setting_data['key'])))
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

    def _update_total_seconds_from_fields(self, *args):
        """Aktualisiert die Gesamtsekunden basierend auf den Tages-, Stunden- und Minutenfeldern."""
        try:
            days = self.days_var.get()
            hours = self.hours_var.get()
            minutes = self.minutes_var.get()

            total_seconds = (days * 86400) + (hours * 3600) + (minutes * 60)
            self.temp_value.set(total_seconds)
            self.total_seconds_label.config(text=f"Gesamt: {total_seconds}s")
        except tk.TclError:
            # Dies kann passieren, wenn die Eingabe ungültig ist (z.B. leeres Feld)
            pass # Ignoriere für jetzt, da Spinboxen dies verhindern sollten

    def on_toggle_sensor_use(self):
        if self.toggle_var.get() == 1:
            self.moisture_spinbox.config(state="normal")
            if self.temp_value.get() == 0:
                self.temp_value.set(current_config.get("moisturemax", DEFAULT_CONFIG["moisturemax"]))
        else:
            self.moisture_spinbox.config(state="disabled")
            self.temp_value.set(0)

    def adjust_value(self, change):
        new_val = self.temp_value.get() + change
        min_val = self.setting_data.get("min", 0)
        max_val = self.setting_data.get("max", 100000)

        new_val = max(min_val, min(max_val, new_val))
        self.temp_value.set(new_val)

    def save_and_close(self):
        key = self.setting_data['key']

        if key == "moisturesensoruse":
            current_config["moisturesensoruse"] = self.toggle_var.get()
            if self.toggle_var.get() == 1:
                current_config["moisturemax"] = self.temp_value.get()
        else:
            current_config[key] = self.temp_value.get()

        save_config()
        messagebox.showinfo("Gespeichert", f"'{self.setting_data['label'].replace(':', '')}' auf {self.temp_value.get()} {self.setting_data.get('unit', '')} gespeichert.")
        self.update_callback()
        self.destroy()

    def cancel_and_close(self):
        self.destroy()

# NEU: Frame für die manuelle Bewässerung
class ManualWateringFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="MANUELLE BEWÄSSERUNG", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=40)

        info_label = tk.Label(self, text="Starten Sie die Pumpe für eine einmalige Bewässerung.", font=("Inter", 16), fg="white", bg="#2c3e50")
        info_label.pack(pady=10, padx=20)

        button_style = {"font": ("Inter", 18), "fg": "white", "padx": 20, "pady": 10, "relief": "raised", "bd": 3, "width": 25}

        # Button, um mit der Standard-Wassermenge zu gießen
        standard_amount = current_config.get("wateringamount", DEFAULT_CONFIG["wateringamount"])
        tk.Button(self, text=f"Standardmenge ({standard_amount} ml)",
                  command=lambda: self.controller.trigger_manual_watering(standard_amount),
                  bg="#27ae60", **button_style).pack(pady=10)

        # Button, um eine benutzerdefinierte Menge einzugeben
        tk.Button(self, text="Benutzerdefinierte Menge",
                  command=lambda: self.controller.trigger_manual_watering(None),
                  bg="#f39c12", **button_style).pack(pady=10)

        # Zurück-Button
        tk.Button(self, text="Zurück zum Hauptmenü",
                  command=lambda: self.controller.show_frame("main_menu"),
                  bg="#e74c3c", **button_style).pack(pady=40)


class ConfirmRepotFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="PFLANZE UMGETOPFT?", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=40)
        tk.Label(self, text="Möchten Sie bestätigen, dass die Pflanze umgetopft wurde?", font=("Inter", 18), fg="white", bg="#2c3e50").pack(pady=20)

        button_style = {"font": ("Inter", 18), "padx": 20, "pady": 10, "relief": "raised", "bd": 3, "width": 15}

        tk.Button(self, text="Ja", command=self.controller.repot_plant_action, bg="#27ae60", fg="white", **button_style).pack(pady=10)
        tk.Button(self, text="Nein (Zurück)", command=lambda: self.controller.show_frame("main_menu"), bg="#e74c3c", fg="white", **button_style).pack(pady=10)

class IdleScreenFrame(BaseMenuFrame):
    def create_widgets(self):
        self.configure(bg="#1a2b3c")

        self.time_label = tk.Label(self, text="", font=("Inter", 48, "bold"), fg="#ecf0f1", bg="#1a2b3c")
        self.time_label.pack(pady=20)

        info_frame = tk.Frame(self, bg="#1a2b3c")
        info_frame.pack(pady=20)

        self.idle_moisture_label = tk.Label(info_frame, text="Feuchtigkeit: --%", font=("Inter", 20), fg="#95a5a6", bg="#1a2b3c")
        self.idle_moisture_label.pack(pady=5)
        self.idle_tank_label = tk.Label(info_frame, text="Tankfüllstand: -- ml (--%)", font=("Inter", 20), fg="#95a5a6", bg="#1a2b3c")
        self.idle_tank_label.pack(pady=5)
        self.idle_remaining_cycles_label = tk.Label(info_frame, text="Verbleibende Gießzyklen: --", font=("Inter", 20), fg="#95a5a6", bg="#1a2b3c")
        self.idle_remaining_cycles_label.pack(pady=5)
        self.idle_next_watering_label = tk.Label(info_frame, text="Nächste Bewässerung in: --", font=("Inter", 20), fg="#95a5a6", bg="#1a2b3c")
        self.idle_next_watering_label.pack(pady=5)

        self.update_idle_data()

    def update_idle_data(self):
        # Uhrzeit aktualisieren
        self.time_label.config(text=datetime.now().strftime("%H:%M:%S"))

        # Sensorwerte und Status aus dem Controller holen
        try:
            moisture = self.controller.ads1115.moisture_sensor_status()
            tank_ml = self.controller.ads1115.tank_level_ml()
            tank_percent = self.controller.ads1115.tank_level()

            self.idle_moisture_label.config(text=f"Feuchtigkeit: {moisture}%")
            self.idle_tank_label.config(text=f"Tankfüllstand: {tank_ml:.2f} ml ({tank_percent}%)")

            # Lade den neuesten Status aus der Datei
            load_watering_status_gui()

            # Verbleibende Gießzyklen anzeigen
            self.idle_remaining_cycles_label.config(text=f"Verbleibende Gießzyklen: {watering_status_gui['remaining_watering_cycles']}")

            # Verbleibende Zeit bis zur nächsten Bewässerung
            if watering_status_gui["estimated_next_watering_time"] is not None:
                remaining_s = watering_status_gui["estimated_next_watering_time"] - time.time()
                if remaining_s < 0:
                    remaining_s = 0 # Sollte nicht negativ sein, wenn der Timer korrekt läuft

                days, remainder = divmod(int(remaining_s), 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)

                self.idle_next_watering_label.config(text=f"Nächste Bewässerung in: {int(days)}T {int(hours)}h {int(minutes)}m {int(seconds)}s")
            else:
                self.idle_next_watering_label.config(text="Nächste Bewässerung: Nicht geplant")

        except Exception as e:
            print(f"Fehler beim Aktualisieren des Idle-Screens: {e}")
            self.idle_moisture_label.config(text="Feuchtigkeit: Fehler")
            self.idle_tank_label.config(text="Tankfüllstand: Fehler")
            self.idle_remaining_cycles_label.config(text="Verbleibende Gießzyklen: Fehler")
            self.idle_next_watering_label.config(text="Nächste Bewässerung: Fehler")

        # self.after(1000, self.update_idle_data) # Dieser Aufruf wurde entfernt, um Doppelungen zu vermeiden


# --- Hauptprogramm-Logik ---
if __name__ == "__main__":
    # Konfiguration laden
    load_config()

    # Hardware initialisieren
    ads1115 = ADS1115()
    # Pump-Instanz hier entfernt, da sie vom Hauptsystem verwaltet wird
    precheck = PreWateringCheck(ads1115) # Hinzugefügt: Initialisierung von precheck

    # GUI-Anwendung starten
    app = PlantWateringApp(ads1115, precheck) # Pump-Instanz hier nicht übergeben

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
        GPIO.cleanup() # Sicherstellen, dass GPIO-Pins bereinigt werden
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")