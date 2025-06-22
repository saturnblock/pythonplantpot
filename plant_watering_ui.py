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
    # PUMP_TIME_ONE_ML hinzugefügt, um die Wassermenge aus der Pumpdauer zu berechnen
    from pi_hardware_utils import ADS1115, RotaryEncoder, Pump, PreWateringCheck, TANK_VOLUME, PUMP_TIME_ONE_ML
except ImportError:
    messagebox.showerror("Import Error", "Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.\n"
                                         "Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
    sys.exit(1)

# --- Globale Konfiguration und Statusdateien ---
CONFIG_FILE = 'config.json'
# PUMP_COMMAND_FILE wurde entfernt, da die Kommunikation nun über config.json läuft.
WATERING_STATUS_FILE = 'watering_status.json'

# Standardwerte für die Pflanzenbewässerung
DEFAULT_CONFIG = {
    "wateringtimer": 60,
    "wateringamount": 20,
    "moisturemax": 50,
    "moisturesensoruse": 1
}

current_config = {}

watering_status_gui = {
    "last_watering_time": None,
    "estimated_next_watering_time": None,
    "remaining_watering_cycles": 0,
    "current_timer_remaining_s": 0
}

# --- Dateifunktionen ---

def load_config():
    """Lädt die Konfiguration aus der config.json-Datei."""
    global current_config
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                current_config = data[0]
            else:
                current_config = DEFAULT_CONFIG
    except (FileNotFoundError, json.JSONDecodeError):
        current_config = DEFAULT_CONFIG
    # Speichern, um sicherzustellen, dass die Datei mit Standardwerten existiert/korrekt ist.
    save_config()

def save_config():
    """Speichert die aktuelle Konfiguration in der config.json-Datei."""
    # Diese Funktion speichert nur die UI-bezogenen Einstellungen.
    # Anfragen werden separat hinzugefügt.
    try:
        with open(CONFIG_FILE, 'w') as f:
            # Wir schreiben immer die 'current_config', um Anfragen nicht zu überschreiben.
            json.dump([current_config], f, indent=4)
        print("Konfiguration erfolgreich gespeichert.")
    except Exception as e:
        print(f"Fehler beim Speichern der Konfiguration in {CONFIG_FILE}: {e}")

def update_config_with_request(request_key, request_data):
    """
    Lädt die config.json, fügt eine Anfrage hinzu und speichert sie wieder.
    Dies ist der neue, sichere Weg, um Befehle zu senden.
    """
    try:
        with open(CONFIG_FILE, 'r') as f:
            # Lade die gesamte Datei, um andere potenziell vorhandene Daten nicht zu verlieren.
            full_config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Wenn die Datei nicht existiert oder leer ist, starte mit der aktuellen Konfiguration.
        full_config_data = [current_config]

    # Füge die Anfrage zum ersten Konfigurationsobjekt hinzu.
    if isinstance(full_config_data, list) and len(full_config_data) > 0:
        full_config_data[0][request_key] = request_data
    else:
        # Fallback, falls die Datei ein unerwartetes Format hat.
        full_config_data = [current_config]
        full_config_data[0][request_key] = request_data

    # Speichere die aktualisierte Konfiguration zurück in die Datei.
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(full_config_data, f, indent=4)
        print(f"Anfrage '{request_key}' erfolgreich in {CONFIG_FILE} geschrieben.")
        return True
    except Exception as e:
        print(f"Fehler beim Schreiben der Anfrage in {CONFIG_FILE}: {e}")
        return False


def load_watering_status_gui():
    """Lädt den Bewässerungsstatus aus der watering_status.json-Datei für die GUI."""
    global watering_status_gui
    try:
        with open(WATERING_STATUS_FILE, 'r') as f:
            data = json.load(f)
            for key in watering_status_gui:
                if key in data:
                    watering_status_gui[key] = data[key]
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass # Normal, wenn die Datei noch nicht existiert.
    except Exception as e:
        print(f"GUI: Unerwarteter Fehler beim Laden des Bewässerungsstatus: {e}")

# --- GUI-Anwendungsklasse ---
class PlantWateringApp(tk.Tk):
    IDLE_TIMEOUT_MS = 60000

    def __init__(self, ads_instance, precheck_instance):
        super().__init__()
        self.title("Pflanzenbewässerungssystem")
        self.geometry("800x480")

        self.ads1115 = ads_instance
        self.precheck = precheck_instance

        self.current_frame = None
        self.frames = {}

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self.create_frames()
        self.create_sensor_status_display()
        self.show_frame("main_menu")

        self.update_sensor_data()

        self.idle_timer_id = None
        self.bind_all('<Any-Key>', self.reset_idle_timer)
        self.bind_all('<Button-1>', self.reset_idle_timer)
        self.reset_idle_timer()

    def create_frames(self):
        self.frames["main_menu"] = MainMenuFrame(self, self)
        self.frames["main_menu"].grid(row=0, column=0, sticky="nsew")

        self.frames["manual_pump"] = ManualPumpFrame(self, self)
        self.frames["manual_pump"].grid(row=0, column=0, sticky="nsew")

        self.frames["watering_settings"] = WateringSettingsFrame(self, self)
        self.frames["watering_settings"].grid(row=0, column=0, sticky="nsew")

        self.frames["confirm_repot"] = ConfirmRepotFrame(self, self)
        self.frames["confirm_repot"].grid(row=0, column=0, sticky="nsew")

        self.frames["idle_screen"] = IdleScreenFrame(self, self)
        self.frames["idle_screen"].grid(row=0, column=0, sticky="nsew")


    def create_sensor_status_display(self):
        self.sensor_status_frame = tk.Frame(self, bg="#34495e", bd=2, relief="groove")
        self.sensor_status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        self.moisture_label = tk.Label(self.sensor_status_frame, text="Feuchtigkeit: --%", font=("Inter", 14), fg="white", bg="#34495e")
        self.moisture_label.grid(row=0, column=0, padx=2, pady=2, sticky="ew")

        self.tank_label = tk.Label(self.sensor_status_frame, text="Tankfüllstand: -- ml (--%)", font=("Inter", 14), fg="white", bg="#34495e")
        self.tank_label.grid(row=0, column=1, padx=2, pady=2, sticky="ew")

        self.remaining_waterings_label = tk.Label(self.sensor_status_frame, text="Verbleibende Gießvorgänge: --", font=("Inter", 14), fg="white", bg="#34495e")
        self.remaining_waterings_label.grid(row=0, column=2, padx=2, pady=2, sticky="ew")

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
        load_watering_status_gui()
        try:
            moisture = self.ads1115.moisture_sensor_status()
            tank_ml = self.ads1115.tank_level_ml()
            tank_percent = self.ads1115.tank_level()

            self.moisture_label.config(text=f"Feuchtigkeit: {moisture}%")
            self.tank_label.config(text=f"Tankfüllstand: {tank_ml:.2f} ml ({tank_percent}%)")
            self.remaining_waterings_label.config(text=f"Verbleibende Gießvorgänge: {watering_status_gui['remaining_watering_cycles']}")

            if self.current_frame == self.frames["idle_screen"]:
                self.frames["idle_screen"].update_idle_data()

        except Exception as e:
            print(f"Fehler beim Lesen der Sensordaten: {e}")
            self.moisture_label.config(text="Feuchtigkeit: Fehler")
            self.tank_label.config(text="Tankfüllstand: Fehler")
            self.remaining_waterings_label.config(text="Gießvorgänge: Fehler")

        self.after(1000, self.update_sensor_data)

    def repot_plant_action(self):
        messagebox.showinfo("Umgetopft", "Pflanze wurde umgetopft!\nSende Befehl zum Zurücksetzen des Gießzyklus...")
        request_data = {"timestamp": time.time()}
        # Der eigentliche Schreibvorgang wird in einem Thread ausgeführt, um die GUI nicht zu blockieren.
        threading.Thread(target=update_config_with_request, args=("repot_reset_request", request_data), daemon=True).start()
        self.show_frame("main_menu")

    def exit_program(self):
        if messagebox.askyesno("Beenden", "Möchten Sie das Programm wirklich beenden?"):
            self.destroy()

    def reset_idle_timer(self, event=None):
        if self.idle_timer_id:
            self.after_cancel(self.idle_timer_id)
        if self.current_frame == self.frames["idle_screen"] and event is not None:
            self.show_frame("main_menu")
        self.idle_timer_id = self.after(self.IDLE_TIMEOUT_MS, self.go_to_idle_screen)

    def go_to_idle_screen(self):
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
        tk.Button(self, text="2. Manuelle Pumpensteuerung", command=lambda: self.controller.show_frame("manual_pump"), **button_style).pack(pady=10)
        tk.Button(self, text="3. Ich habe umgetopft!", command=lambda: self.controller.show_frame("confirm_repot"), **button_style).pack(pady=10)
        tk.Button(self, text="4. Programm beenden", command=self.controller.exit_program, **button_style).pack(pady=10)
        tk.Button(self, text="5. Zum Idle-Screen", command=lambda: self.controller.show_frame("idle_screen"), **button_style).pack(pady=10)

class ManualPumpFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="MANUELLE PUMPENSTEUERUNG", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)
        tk.Label(self, text="Pumpe für eine bestimmte Dauer manuell starten.", font=("Inter", 16), fg="white", bg="#2c3e50").pack(pady=10)
        button_style = {"font": ("Inter", 18), "bg": "#16a085", "fg": "white", "padx": 20, "pady": 10, "relief": "raised", "bd": 3, "width": 25}

        tk.Button(self, text="2 Sekunden pumpen", command=lambda: self.initiate_manual_pump(2), **button_style).pack(pady=10)
        tk.Button(self, text="5 Sekunden pumpen", command=lambda: self.initiate_manual_pump(5), **button_style).pack(pady=10)
        tk.Button(self, text="10 Sekunden pumpen", command=lambda: self.initiate_manual_pump(10), **button_style).pack(pady=10)

        tk.Button(self, text="Zurück zum Hauptmenü", font=("Inter", 18), bg="#e74c3c", fg="white",
                  command=lambda: self.controller.show_frame("main_menu"), padx=20, pady=10, relief="raised", bd=3, width=25).pack(pady=40)

    def initiate_manual_pump(self, seconds):
        try:
            if PUMP_TIME_ONE_ML <= 0:
                messagebox.showerror("Konfigurationsfehler", "PUMP_TIME_ONE_ML ist Null. Menge kann nicht berechnet werden.")
                return

            amount_ml = seconds / PUMP_TIME_ONE_ML
            messagebox.showinfo("Anfrage gesendet", f"Anfrage zum Pumpen von ca. {amount_ml:.1f} ml gesendet.")

            request_data = {"amount_ml": amount_ml, "timestamp": time.time()}
            threading.Thread(target=update_config_with_request, args=("manual_pump_request", request_data), daemon=True).start()

        except NameError:
            messagebox.showerror("Importfehler", "Die Konstante 'PUMP_TIME_ONE_ML' konnte nicht geladen werden.")

class WateringSettingsFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="GIESSEINSTELLUNGEN", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)

        self.setting_vars = {}
        self.settings_data = [
            {"label": "1. Gießmenge:", "key": "wateringamount", "unit": "ml", "min": 10, "max": 500, "step": 10},
            {"label": "2. Gießintervall:", "key": "wateringtimer", "type": "time_duration", "unit": "s", "min": 60, "max": 86400, "step": 3600},
            {"label": "3. Feuchtigkeitssensor:", "key": "moisturesensoruse", "type": "toggle_and_value", "min_moisture": 5, "max_moisture": 100, "step_moisture": 5},
        ]

        for setting in self.settings_data:
            frame = tk.Frame(self, bg="#2c3e50")
            frame.pack(pady=5, fill="x", padx=50)

            tk.Label(frame, text=setting["label"], font=("Inter", 16), fg="white", bg="#2c3e50", anchor="w").pack(side="left", padx=10, fill="x", expand=True)

            var = tk.StringVar(self)
            self.setting_vars[setting["key"]] = var
            tk.Label(frame, textvariable=var, font=("Inter", 16, "bold"), fg="#2ecc71", bg="#2c3e50", width=15, anchor="e").pack(side="left", padx=10)

            tk.Button(frame, text="Bearbeiten", font=("Inter", 14), bg="#f39c12", fg="white",
                      command=lambda s=setting: self.open_editor(s)).pack(side="right", padx=10)

        tk.Button(self, text="Zurück zum Hauptmenü", font=("Inter", 18), bg="#e74c3c", fg="white",
                  command=lambda: self.controller.show_frame("main_menu"), padx=20, pady=10, relief="raised", bd=3, width=25).pack(pady=20)

        self.update_display_values()

    def update_display_values(self):
        for key, var in self.setting_vars.items():
            value = current_config.get(key, DEFAULT_CONFIG.get(key))
            if key == "moisturesensoruse":
                if value == 0:
                    var.set("AUS")
                else:
                    var.set(f"{current_config.get('moisturemax', DEFAULT_CONFIG['moisturemax'])}%")
            elif key == "wateringtimer":
                days, remainder = divmod(value, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, _ = divmod(remainder, 60)
                var.set(f"{int(days)}T {int(hours)}h {int(minutes)}m")
            else:
                var.set(f"{value} {self.get_unit_for_key(key)}")

    def get_unit_for_key(self, key):
        for setting in self.settings_data:
            if setting["key"] == key:
                return setting.get("unit", "")
        return ""

    def open_editor(self, setting):
        editor = SettingEditorFrame(self.controller, setting, self.update_display_values)
        self.wait_window(editor)


class SettingEditorFrame(tk.Toplevel):
    def __init__(self, controller, setting_data, update_callback):
        super().__init__(controller)
        self.title(f"Bearbeite: {setting_data['label'].replace(':', '')}")
        self.transient(controller)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.controller = controller
        self.setting_data = setting_data
        self.update_callback = update_callback

        self.configure(bg="#34495e", bd=5, relief="groove")
        self.create_editor_widgets()

    def create_editor_widgets(self):
        tk.Label(self, text=f"Bearbeite: {self.setting_data['label'].replace(':', '')}", font=("Inter", 20, "bold"), fg="white", bg="#34495e").pack(pady=10)

        key = self.setting_data['key']
        if key == "moisturesensoruse":
            self._create_moisture_editor()
        elif self.setting_data.get('type') == "time_duration":
            self._create_time_editor()
        else:
            self._create_numeric_editor()

        tk.Button(self, text="Bestätigen", font=("Inter", 18), bg="#2980b9", fg="white", command=self.save_and_close, padx=20, pady=10).pack(pady=10)
        tk.Button(self, text="Abbrechen", font=("Inter", 18), bg="#c0392b", fg="white", command=self.destroy, padx=20, pady=10).pack(pady=10)

    def _create_moisture_editor(self):
        self.toggle_var = tk.IntVar(self, value=current_config.get("moisturesensoruse", 1))
        self.temp_value = tk.IntVar(self, value=current_config.get("moisturemax", 50))

        frame = tk.Frame(self, bg="#34495e")
        frame.pack(pady=10)

        tk.Checkbutton(frame, text="Sensor verwenden", variable=self.toggle_var, font=("Inter", 16), fg="white", bg="#34495e", selectcolor="#2c3e50", command=self._on_toggle_sensor).pack(side="left", padx=10)

        self.moisture_spinbox = tk.Spinbox(frame, from_=5, to=100, increment=5, textvariable=self.temp_value, font=("Inter", 16), width=5)
        self.moisture_spinbox.pack(side="left", padx=10)
        tk.Label(frame, text="%", font=("Inter", 16), fg="white", bg="#34495e").pack(side="left")
        self._on_toggle_sensor()

    def _on_toggle_sensor(self):
        self.moisture_spinbox.config(state="normal" if self.toggle_var.get() == 1 else "disabled")

    def _create_time_editor(self):
        total_seconds = current_config.get(self.setting_data['key'], 60)
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)

        self.days_var = tk.IntVar(self, value=int(days))
        self.hours_var = tk.IntVar(self, value=int(hours))
        self.minutes_var = tk.IntVar(self, value=int(minutes))

        frame = tk.Frame(self, bg="#34495e")
        frame.pack(pady=10)

        tk.Label(frame, text="Tage:", font=("Inter", 16), fg="white", bg="#34495e").grid(row=0, column=0)
        tk.Spinbox(frame, from_=0, to=365, textvariable=self.days_var, font=("Inter", 16), width=5).grid(row=0, column=1)
        tk.Label(frame, text="Stunden:", font=("Inter", 16), fg="white", bg="#34495e").grid(row=1, column=0)
        tk.Spinbox(frame, from_=0, to=23, textvariable=self.hours_var, font=("Inter", 16), width=5).grid(row=1, column=1)
        tk.Label(frame, text="Minuten:", font=("Inter", 16), fg="white", bg="#34495e").grid(row=2, column=0)
        tk.Spinbox(frame, from_=0, to=59, textvariable=self.minutes_var, font=("Inter", 16), width=5).grid(row=2, column=1)

    def _create_numeric_editor(self):
        self.temp_value = tk.IntVar(self, value=current_config.get(self.setting_data['key'], 0))

        frame = tk.Frame(self, bg="#34495e")
        frame.pack(pady=10)

        tk.Button(frame, text="<", font=("Inter", 20), command=lambda: self._adjust_value(-self.setting_data.get("step", 1))).pack(side="left")
        tk.Label(frame, textvariable=self.temp_value, font=("Inter", 24, "bold"), width=8).pack(side="left")
        tk.Button(frame, text=">", font=("Inter", 20), command=lambda: self._adjust_value(self.setting_data.get("step", 1))).pack(side="left")

    def _adjust_value(self, change):
        new_val = self.temp_value.get() + change
        min_val = self.setting_data.get("min", 0)
        max_val = self.setting_data.get("max", 1000)
        self.temp_value.set(max(min_val, min(max_val, new_val)))

    def save_and_close(self):
        key = self.setting_data['key']

        if key == "moisturesensoruse":
            current_config["moisturesensoruse"] = self.toggle_var.get()
            current_config["moisturemax"] = self.temp_value.get()
        elif self.setting_data.get('type') == "time_duration":
            total_seconds = (self.days_var.get() * 86400) + (self.hours_var.get() * 3600) + (self.minutes_var.get() * 60)
            current_config[key] = total_seconds
        else:
            current_config[key] = self.temp_value.get()

        save_config()
        self.update_callback()
        self.destroy()


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

    def update_idle_data(self):
        self.time_label.config(text=datetime.now().strftime("%H:%M:%S"))
        try:
            moisture = self.controller.ads1115.moisture_sensor_status()
            tank_ml = self.controller.ads1115.tank_level_ml()
            tank_percent = self.controller.ads1115.tank_level()

            self.idle_moisture_label.config(text=f"Feuchtigkeit: {moisture}%")
            self.idle_tank_label.config(text=f"Tankfüllstand: {tank_ml:.2f} ml ({tank_percent}%)")

            load_watering_status_gui()
            self.idle_remaining_cycles_label.config(text=f"Verbleibende Gießzyklen: {watering_status_gui['remaining_watering_cycles']}")

            if watering_status_gui.get("estimated_next_watering_time"):
                remaining_s = watering_status_gui["estimated_next_watering_time"] - time.time()
                remaining_s = max(0, remaining_s)
                days, rem = divmod(int(remaining_s), 86400)
                hours, rem = divmod(rem, 3600)
                minutes, sec = divmod(rem, 60)
                self.idle_next_watering_label.config(text=f"Nächste Bewässerung in: {days}T {hours}h {minutes}m {sec}s")
            else:
                self.idle_next_watering_label.config(text="Nächste Bewässerung: Nicht geplant")
        except Exception as e:
            print(f"Fehler beim Aktualisieren des Idle-Screens: {e}")
        finally:
            self.after(1000, self.update_idle_data)


# --- Hauptprogramm-Logik ---
if __name__ == "__main__":
    try:
        load_config()
        ads1115 = ADS1115()
        precheck = PreWateringCheck(ads1115)
        app = PlantWateringApp(ads1115, precheck)
        app.mainloop()
    except Exception as e:
        print(f"\nEin Fehler ist während der Ausführung aufgetreten: {e}")
        import traceback
        traceback.print_exc()
    finally:
        GPIO.cleanup()
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")
