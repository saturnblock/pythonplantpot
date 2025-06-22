import tkinter as tk
from tkinter import messagebox
import json
import time
import threading
import sys
from datetime import datetime

# Annahme, dass RPi.GPIO auf einem Raspberry Pi verfügbar ist.
# Für Tests auf anderen Systemen kann dies auskommentiert werden.
try:
    import RPi.GPIO as GPIO
except (ImportError, RuntimeError):
    print("Warnung: RPi.GPIO konnte nicht importiert werden. Laufe im Mock-Modus.")
    # Mock-GPIO für Testzwecke auf Nicht-Pi-Systemen
    class MockGPIO:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None
    GPIO = MockGPIO()

# Importiere die Hardware-Utilities
try:
    from pi_hardware_utils import ADS1115, TANK_VOLUME
except ImportError:
    messagebox.showerror("Import Error", "Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.\n"
                                         "Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
    sys.exit(1)

# --- Globale Konfiguration und Statusdateien ---
CONFIG_FILE = 'config.json'
PUMP_COMMAND_FILE = 'pump_command.json'
WATERING_STATUS_FILE = 'watering_status.json'

# Standardwerte für die Pflanzenbewässerung
DEFAULT_CONFIG = {
    "wateringtimer": 3600,
    "wateringamount": 50,
    "moisturemax": 50,
    "moisturesensoruse": 1
}

current_config = {}

# --- Helper-Klasse für Daten-Updates aus dem Hintergrund ---
class HardwareMonitor(threading.Thread):
    """
    Ein Thread, der periodisch Sensordaten und Statusdateien liest,
    um die Haupt-GUI nicht zu blockieren.
    """
    def __init__(self, app_controller, ads_instance):
        super().__init__(daemon=True)
        self.controller = app_controller
        self.ads1115 = ads_instance
        self.stop_event = threading.Event()
        self.latest_data = {
            "moisture": 0,
            "tank_ml": 0.0,
            "tank_percent": 0,
            "status": {}
        }

    def run(self):
        """Hauptschleife des Threads."""
        while not self.stop_event.is_set():
            try:
                moisture = self.ads1115.moisture_sensor_status()
                tank_ml = self.ads1115.tank_level_ml()
                tank_percent = self.ads1115.tank_level()

                status = {}
                try:
                    with open(WATERING_STATUS_FILE, 'r') as f:
                        status = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    pass

                self.latest_data = {
                    "moisture": moisture,
                    "tank_ml": tank_ml,
                    "tank_percent": tank_percent,
                    "status": status
                }

                self.controller.event_generate("<<DataUpdated>>", when="tail")

            except Exception as e:
                print(f"Fehler im HardwareMonitor-Thread: {e}")

            time.sleep(1)

    def stop(self):
        self.stop_event.set()

# --- Funktionen zum Laden/Speichern der Konfiguration ---
def load_config():
    global current_config
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            current_config = data[0] if isinstance(data, list) and data else DEFAULT_CONFIG
    except (FileNotFoundError, json.JSONDecodeError):
        current_config = DEFAULT_CONFIG
        save_config()

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump([current_config], f, indent=4)
        print("Konfiguration gespeichert.")
    except Exception as e:
        print(f"Fehler beim Speichern der Konfiguration: {e}")

def send_pump_command(action, amount_ml=None, duration_s=None):
    try:
        command_data = {"action": action, "amount_ml": amount_ml, "duration_s": duration_s}
        with open(PUMP_COMMAND_FILE, 'w') as f:
            json.dump(command_data, f)

        max_wait_time = 15
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            time.sleep(0.2)
            try:
                with open(PUMP_COMMAND_FILE, 'r') as f:
                    content = f.read().strip()
                if not content or json.loads(content).get("action") == "none":
                    return True
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        return False
    except Exception as e:
        print(f"Fehler beim Senden des Pumpenbefehls: {e}")
        return False

# --- GUI-Anwendungsklasse ---
class PlantWateringApp(tk.Tk):
    IDLE_TIMEOUT_MS = 60000

    def __init__(self, ads_instance):
        super().__init__()
        self.title("Pflanzenbewässerungssystem")
        self.geometry("800x480")
        # self.attributes('-fullscreen', True)

        self.current_frame = None
        self.frames = {}

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self.create_frames()
        self.create_sensor_status_display()

        self.hardware_monitor = HardwareMonitor(self, ads_instance)
        self.hardware_monitor.start()

        self.bind("<<DataUpdated>>", self.update_ui_from_monitor)

        self.idle_timer_id = None
        self.bind_all('<Any-Key>', self.reset_idle_timer)
        self.bind_all('<Button-1>', self.reset_idle_timer)

        self.show_frame("mainmenu") # KORRIGIERT
        self.reset_idle_timer()

    def create_frames(self):
        for F in (MainMenuFrame, WateringSettingsFrame, ManualControlFrame, RepotConfigFrame, IdleScreenFrame):
            frame_name = F.__name__.replace("Frame", "").lower()
            frame = F(self, self)
            self.frames[frame_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

    def create_sensor_status_display(self):
        self.sensor_status_frame = tk.Frame(self, bg="#34495e", bd=2, relief="groove")
        self.sensor_status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        for i in range(3):
            self.sensor_status_frame.grid_columnconfigure(i, weight=1)

        self.moisture_label = tk.Label(self.sensor_status_frame, text="Feuchtigkeit: --%", font=("Inter", 14), fg="white", bg="#34495e")
        self.moisture_label.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        self.tank_label = tk.Label(self.sensor_status_frame, text="Tankfüllstand: -- ml", font=("Inter", 14), fg="white", bg="#34495e")
        self.tank_label.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        self.remaining_waterings_label = tk.Label(self.sensor_status_frame, text="Gießvorgänge: --", font=("Inter", 14), fg="white", bg="#34495e")
        self.remaining_waterings_label.grid(row=0, column=2, padx=2, pady=2, sticky="ew")

    def show_frame(self, frame_name):
        # KORREKTUR: Sicherstellen, dass der Frame-Name existiert
        if frame_name not in self.frames:
            print(f"Fehler: Frame '{frame_name}' nicht gefunden!")
            return

        frame = self.frames[frame_name]
        self.current_frame = frame
        if hasattr(frame, 'on_show'):
            frame.on_show()
        frame.tkraise()

    def update_ui_from_monitor(self, event=None):
        data = self.hardware_monitor.latest_data
        status = data.get("status", {})

        self.moisture_label.config(text=f"Feuchtigkeit: {data['moisture']}%")
        self.tank_label.config(text=f"Tank: {data['tank_ml']:.0f}ml ({data['tank_percent']}%)")
        self.remaining_waterings_label.config(text=f"Gießvorgänge: {status.get('remaining_watering_cycles', '--')}")

        if hasattr(self.current_frame, 'update_data'):
            self.current_frame.update_data(data)

    def exit_program(self):
        if messagebox.askyesno("Beenden", "Möchten Sie das Programm wirklich beenden?"):
            self.hardware_monitor.stop()
            self.destroy()

    def reset_idle_timer(self, event=None):
        if self.idle_timer_id:
            self.after_cancel(self.idle_timer_id)
        if self.current_frame == self.frames.get("idlescreen"): # KORRIGIERT
            self.show_frame("mainmenu") # KORRIGIERT
        self.idle_timer_id = self.after(self.IDLE_TIMEOUT_MS, lambda: self.show_frame("idlescreen")) # KORRIGIERT

# --- Frame-Klassen ---
class BaseMenuFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg="#2c3e50")
        self.controller = controller
        self.create_widgets()
    def create_widgets(self):
        raise NotImplementedError

class MainMenuFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="HAUPTMENÜ", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)
        button_style = {"font": ("Inter", 18), "bg": "#3498db", "fg": "white", "padx": 20, "pady": 10, "relief": "raised", "bd": 3, "width": 25}
        tk.Button(self, text="1. Gießeinstellungen", command=lambda: self.controller.show_frame("wateringsettings"), **button_style).pack(pady=10)
        tk.Button(self, text="2. Manuelle Steuerung", command=lambda: self.controller.show_frame("manualcontrol"), **button_style).pack(pady=10)
        tk.Button(self, text="3. Ich habe umgetopft!", command=lambda: self.controller.show_frame("repotconfig"), **button_style).pack(pady=10)
        tk.Button(self, text="4. Programm beenden", command=self.controller.exit_program, **button_style).pack(pady=10)

class WateringSettingsFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="GIESSEINSTELLUNGEN", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)
        self.setting_vars = {}
        self.settings_data = [
            {"label": "Gießmenge:", "key": "wateringamount", "unit": "ml"},
            {"label": "Gießintervall:", "key": "wateringtimer", "type": "time_duration"},
            {"label": "Feuchtigkeitsschwelle:", "key": "moisturesensoruse", "type": "toggle_and_value"},
        ]
        for setting in self.settings_data:
            frame = tk.Frame(self, bg="#2c3e50")
            frame.pack(pady=5, fill="x", padx=50)
            tk.Label(frame, text=setting["label"], font=("Inter", 16), fg="white", bg="#2c3e50", anchor="w").pack(side="left", padx=10, fill="x", expand=True)
            var = tk.StringVar(self)
            self.setting_vars[setting["key"]] = var
            tk.Label(frame, textvariable=var, font=("Inter", 16, "bold"), fg="#2ecc71", bg="#2c3e50", width=15, anchor="e").pack(side="left", padx=10)
            tk.Button(frame, text="Bearbeiten", font=("Inter", 14), bg="#f39c12", fg="white", command=lambda s=setting: self.open_editor(s)).pack(side="right", padx=10)
        tk.Button(self, text="Zurück", font=("Inter", 18), bg="#e74c3c", fg="white", command=lambda: self.controller.show_frame("mainmenu")).pack(pady=20)

    def on_show(self):
        self.update_display_values()

    def update_display_values(self):
        load_config()
        for key, var in self.setting_vars.items():
            if key == "moisturesensoruse":
                var.set("AUS" if current_config.get(key) == 0 else f"EIN (< {current_config.get('moisturemax')}%)")
            elif key == "wateringtimer":
                days, rem = divmod(current_config.get(key, 0), 86400)
                hours, rem = divmod(rem, 3600)
                minutes, _ = divmod(rem, 60)
                var.set(f"{int(days)}T {int(hours)}h {int(minutes)}m")
            else:
                var.set(f"{current_config.get(key)} {next((s.get('unit', '') for s in self.settings_data if s['key'] == key), '')}")

    def open_editor(self, setting):
        editor = SettingEditorFrame(self.controller, setting, self.update_display_values)
        editor.grab_set()

class SettingEditorFrame(tk.Toplevel):
    def __init__(self, controller, setting_data, update_callback):
        super().__init__(controller, bg="#34495e", bd=5, relief="groove")
        self.title(f"Bearbeite: {setting_data['label']}")
        self.transient(controller)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.setting_data = setting_data
        self.update_callback = update_callback
        self.create_editor_widgets()

    def create_editor_widgets(self):
        key = self.setting_data['key']
        tk.Label(self, text=self.setting_data['label'], font=("Inter", 20, "bold"), fg="white", bg="#34495e").pack(pady=10)

        content_frame = tk.Frame(self, bg="#34495e")
        content_frame.pack(pady=10, padx=20)

        if key == "moisturesensoruse":
            self.sensor_on = tk.IntVar(value=current_config.get("moisturesensoruse"))
            self.moisture_max = tk.IntVar(value=current_config.get("moisturemax"))
            tk.Checkbutton(content_frame, text="Sensor aktiv", variable=self.sensor_on, font=("Inter", 16), fg="white", bg="#34495e", selectcolor="#2c3e50").pack(anchor="w")

            tk.Label(content_frame, text="Schwelle (%):", font=("Inter", 16), fg="white", bg="#34495e").pack(anchor="w", pady=(10,0))
            tk.Spinbox(content_frame, from_=10, to=90, increment=5, textvariable=self.moisture_max, font=("Inter", 16), width=5).pack(anchor="w")
        elif self.setting_data.get('type') == "time_duration":
            total_seconds = current_config.get(key, 0)
            self.hours = tk.IntVar(value=total_seconds // 3600)
            tk.Label(content_frame, text="Intervall (Stunden):", font=("Inter", 16), fg="white", bg="#34495e").pack()
            tk.Spinbox(content_frame, from_=0, to=168, textvariable=self.hours, font=("Inter", 16), width=5).pack()
        else: # Gießmenge
            self.amount = tk.IntVar(value=current_config.get(key))
            tk.Label(content_frame, text="Menge (ml):", font=("Inter", 16), fg="white", bg="#34495e").pack()
            tk.Spinbox(content_frame, from_=10, to=500, increment=10, textvariable=self.amount, font=("Inter", 16), width=5).pack()

        btn_frame = tk.Frame(self, bg="#34495e")
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Bestätigen", font=("Inter", 14), command=self.save_and_close).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Abbrechen", font=("Inter", 14), command=self.destroy).pack(side="left", padx=10)

    def save_and_close(self):
        key = self.setting_data['key']
        if key == "moisturesensoruse":
            current_config["moisturesensoruse"] = self.sensor_on.get()
            current_config["moisturemax"] = self.moisture_max.get()
        elif self.setting_data.get('type') == "time_duration":
            current_config[key] = self.hours.get() * 3600
        else:
            current_config[key] = self.amount.get()
        save_config()
        self.update_callback()
        self.destroy()

class ManualControlFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="MANUELLE STEUERUNG", font=("Inter", 24, "bold"), fg="white", bg="#2c3e50").pack(pady=20)
        tk.Button(self, text="Pumpe für 10s starten", font=("Inter", 16), command=self.start_pump_10s).pack(pady=10, padx=20, fill="x")
        tk.Frame(self, height=2, bg="white").pack(fill="x", padx=50, pady=20)

        amount_frame = tk.Frame(self, bg="#2c3e50")
        amount_frame.pack(pady=10, padx=20)
        self.manual_amount_ml = tk.IntVar(value=50)
        tk.Label(amount_frame, text="Gießmenge (ml):", font=("Inter", 16), fg="white", bg="#2c3e50").grid(row=0, column=0, pady=5)
        tk.Spinbox(amount_frame, from_=10, to=500, increment=10, textvariable=self.manual_amount_ml, font=("Inter", 16), width=6).grid(row=0, column=1, pady=5)
        tk.Button(amount_frame, text="Pumpe mit Menge starten", font=("Inter", 16), command=self.start_pump_ml).grid(row=1, columnspan=2, pady=10, sticky="ew")

        tk.Button(self, text="Zurück", font=("Inter", 18), bg="#e74c3c", fg="white", command=lambda: self.controller.show_frame("mainmenu")).pack(pady=40)

    def start_pump_10s(self):
        threading.Thread(target=self._send_command_thread, args=("pump_timed", None, 10), daemon=True).start()
    def start_pump_ml(self):
        threading.Thread(target=self._send_command_thread, args=("pump_manual", self.manual_amount_ml.get(), None), daemon=True).start()

    def _send_command_thread(self, action, amount, duration):
        self.controller.after(0, lambda: messagebox.showinfo("Sende...", f"Sende Befehl: {action}"))
        if send_pump_command(action=action, amount_ml=amount, duration_s=duration):
            self.controller.after(0, lambda: messagebox.showinfo("Erfolg", "Befehl verarbeitet."))
        else:
            self.controller.after(0, lambda: messagebox.showerror("Fehler", "Timeout bei Befehlsverarbeitung."))

class RepotConfigFrame(BaseMenuFrame):
    def create_widgets(self):
        tk.Label(self, text="NEUE KONFIGURATION", font=("Inter", 20, "bold"), fg="white", bg="#2c3e50").pack(pady=15)
        self.vars = {"wateringamount": tk.IntVar(), "wateringtimer": tk.IntVar(), "moisturemax": tk.IntVar(), "moisturesensoruse": tk.IntVar()}

        settings_frame = tk.Frame(self, bg="#2c3e50")
        settings_frame.pack(pady=10, padx=20)
        tk.Label(settings_frame, text="Gießmenge (ml):", font=("Inter", 14), fg="white", bg="#2c3e50").grid(row=0, column=0, sticky="w", pady=5)
        tk.Spinbox(settings_frame, from_=10, to=500, increment=10, textvariable=self.vars["wateringamount"], font=("Inter", 14), width=7).grid(row=0, column=1, padx=5)
        tk.Label(settings_frame, text="Intervall (Stunden):", font=("Inter", 14), fg="white", bg="#2c3e50").grid(row=1, column=0, sticky="w", pady=5)
        tk.Spinbox(settings_frame, from_=1, to=168, textvariable=self.vars["wateringtimer"], font=("Inter", 14), width=7).grid(row=1, column=1, padx=5)
        tk.Checkbutton(settings_frame, text="Feuchtesensor nutzen?", variable=self.vars["moisturesensoruse"], font=("Inter", 14), fg="white", bg="#2c3e50", selectcolor="#34495e", anchor="w").grid(row=2, column=0, columnspan=2, sticky="w", pady=5)
        tk.Label(settings_frame, text="Schwelle (%):", font=("Inter", 14), fg="white", bg="#2c3e50").grid(row=3, column=0, sticky="w", pady=5)
        tk.Spinbox(settings_frame, from_=10, to=90, increment=5, textvariable=self.vars["moisturemax"], font=("Inter", 14), width=7).grid(row=3, column=1, padx=5)

        btn_frame = tk.Frame(self, bg="#2c3e50")
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Bestätigen & Neustart", font=("Inter", 16), bg="#27ae60", fg="white", command=self.save_and_reset).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Abbrechen", font=("Inter", 16), bg="#e74c3c", fg="white", command=lambda: self.controller.show_frame("mainmenu")).pack(side="left", padx=10)

    def on_show(self):
        load_config()
        self.vars["wateringamount"].set(current_config.get("wateringamount", DEFAULT_CONFIG["wateringamount"]))
        self.vars["wateringtimer"].set(int(current_config.get("wateringtimer", DEFAULT_CONFIG["wateringtimer"]) / 3600))
        self.vars["moisturemax"].set(current_config.get("moisturemax", DEFAULT_CONFIG["moisturemax"]))
        self.vars["moisturesensoruse"].set(current_config.get("moisturesensoruse", DEFAULT_CONFIG["moisturesensoruse"]))

    def save_and_reset(self):
        current_config["wateringamount"] = self.vars["wateringamount"].get()
        current_config["wateringtimer"] = self.vars["wateringtimer"].get() * 3600
        current_config["moisturemax"] = self.vars["moisturemax"].get()
        current_config["moisturesensoruse"] = self.vars["moisturesensoruse"].get()
        save_config()
        messagebox.showinfo("Gespeichert", "Neue Konfiguration gespeichert.")
        threading.Thread(target=lambda: send_pump_command("repot_reset"), daemon=True).start()
        self.controller.show_frame("mainmenu")

class IdleScreenFrame(BaseMenuFrame):
    def create_widgets(self):
        self.configure(bg="#1a2b3c")
        self.time_label = tk.Label(self, text="", font=("Inter", 48, "bold"), fg="#ecf0f1", bg="#1a2b3c")
        self.time_label.pack(pady=20)
        info_frame = tk.Frame(self, bg="#1a2b3c")
        info_frame.pack(pady=20)
        self.idle_moisture_label = tk.Label(info_frame, font=("Inter", 20), fg="#95a5a6", bg="#1a2b3c")
        self.idle_moisture_label.pack(pady=5)
        self.idle_tank_label = tk.Label(info_frame, font=("Inter", 20), fg="#95a5a6", bg="#1a2b3c")
        self.idle_tank_label.pack(pady=5)
        self.idle_next_watering_label = tk.Label(info_frame, font=("Inter", 20), fg="#95a5a6", bg="#1a2b3c")
        self.idle_next_watering_label.pack(pady=5)
        self.update_time()

    def update_time(self):
        self.time_label.config(text=datetime.now().strftime("%H:%M:%S"))
        self.after(1000, self.update_time)

    def update_data(self, data):
        status = data.get("status", {})
        self.idle_moisture_label.config(text=f"Feuchtigkeit: {data.get('moisture', '--')}%")
        self.idle_tank_label.config(text=f"Tank: {data.get('tank_ml', 0.0):.0f}ml ({data.get('tank_percent', '--')}%)")

        next_time = status.get("estimated_next_watering_time")
        if next_time:
            remaining_s = max(0, next_time - time.time())
            hours, rem = divmod(int(remaining_s), 3600)
            minutes, seconds = divmod(rem, 60)
            self.idle_next_watering_label.config(text=f"Nächstes Gießen in: {hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.idle_next_watering_label.config(text="Nächstes Gießen: Unbekannt")

# --- Hauptprogramm-Logik ---
if __name__ == "__main__":
    try:
        load_config()
        ads1115 = ADS1115()
        app = PlantWateringApp(ads1115)
        app.mainloop()
    except Exception as e:
        print(f"\nEin kritischer Fehler ist beim Start aufgetreten: {e}")
        import traceback
        traceback.print_exc()
    finally:
        GPIO.cleanup()
        print("Programm beendet.")
