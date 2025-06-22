import tkinter as tk
from tkinter import messagebox, simpledialog
import json
import time
import threading
import os
import sys
from datetime import datetime, timedelta
import RPi.GPIO as GPIO
import queue  # NEU: Importiere die Queue-Bibliothek

# Importiere die Hardware-Utilities
try:
    from pi_hardware_utils import ADS1115, RotaryEncoder, Pump, PreWateringCheck, TANK_VOLUME
except ImportError:
    messagebox.showerror("Import Error", "Fehler: 'pi_hardware_utils.py' konnte nicht gefunden werden.\n"
                                         "Bitte stellen Sie sicher, dass 'pi_hardware_utils.py' im selben Verzeichnis liegt.")
    sys.exit(1)

# --- (Der Rest der globalen Konfiguration und Funktionen bleibt unverändert) ---
# --- (load_config, save_config, load_watering_status_gui, send_pump_command) ---
CONFIG_FILE = 'config.json'
PUMP_COMMAND_FILE = 'pump_command.json'
WATERING_STATUS_FILE = 'watering_status.json'

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

def load_config():
    global current_config
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0: current_config = data[0]
            else: current_config = DEFAULT_CONFIG; save_config()
    except (FileNotFoundError, json.JSONDecodeError):
        current_config = DEFAULT_CONFIG; save_config()

def save_config():
    with open(CONFIG_FILE, 'w') as f: json.dump([current_config], f, indent=4)

def load_watering_status_gui():
    global watering_status_gui
    try:
        with open(WATERING_STATUS_FILE, 'r') as f:
            data = json.load(f)
            for key in watering_status_gui:
                if key in data: watering_status_gui[key] = data[key]
    except (FileNotFoundError, json.JSONDecodeError): pass

def send_pump_command(amount_ml=None, action="pump_manual"):
    try:
        command_data = {"action": action}
        if amount_ml is not None: command_data["amount_ml"] = amount_ml
        with open(PUMP_COMMAND_FILE, 'w') as f: json.dump(command_data, f)

        start_time = time.time()
        while time.time() - start_time < 10:
            try:
                with open(PUMP_COMMAND_FILE, 'r') as f:
                    if json.load(f).get("action") == "none": return True
            except (FileNotFoundError, json.JSONDecodeError): pass
            time.sleep(0.1)
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
        self.geometry("800x480")

        self.ads1115 = ads_instance
        self.precheck = precheck_instance

        # NEU: Erstelle eine Queue für die Thread-Kommunikation
        self.queue = queue.Queue()

        self.current_frame = None
        self.frames = {}

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self.create_frames()
        self.create_sensor_status_display()
        self.show_frame("main_menu")

        self.update_sensor_data()
        self.reset_idle_timer()

        # NEU: Starte den Prozess, der die Queue auf Nachrichten überprüft
        self.process_queue()

    # NEU: Eine Methode, die periodisch die Queue auf Nachrichten vom Thread überprüft
    def process_queue(self):
        try:
            # Holt eine Nachricht aus der Queue, ohne zu blockieren
            message = self.queue.get_nowait()

            # Zeigt die Nachricht sicher im Haupt-Thread an
            msg_type, title, text = message
            if msg_type == 'info':
                messagebox.showinfo(title, text)
            elif msg_type == 'error':
                messagebox.showerror(title, text)

        except queue.Empty:
            # Wenn die Queue leer ist, passiert nichts
            pass
        finally:
            # Plane die nächste Überprüfung in 100ms
            self.after(100, self.process_queue)

    def create_frames(self):
        # ... (unverändert)
        self.frames["main_menu"] = MainMenuFrame(self, self)
        self.frames["main_menu"].grid(row=0, column=0, sticky="nsew")
        self.frames["watering_settings"] = WateringSettingsFrame(self, self)
        self.frames["watering_settings"].grid(row=0, column=0, sticky="nsew")
        self.frames["manual_watering"] = ManualWateringFrame(self, self)
        self.frames["manual_watering"].grid(row=0, column=0, sticky="nsew")
        self.frames["confirm_repot"] = ConfirmRepotFrame(self, self)
        self.frames["confirm_repot"].grid(row=0, column=0, sticky="nsew")
        self.frames["idle_screen"] = IdleScreenFrame(self, self)
        self.frames["idle_screen"].grid(row=0, column=0, sticky="nsew")

    def create_sensor_status_display(self):
        # ... (unverändert)
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
        # ... (unverändert)
        frame = self.frames[frame_name]
        frame.tkraise()
        self.current_frame = frame
        if frame_name == "watering_settings": frame.update_display_values()
        elif frame_name == "idle_screen": frame.update_idle_data()

    def update_sensor_data(self):
        # ... (unverändert)
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
        self.after(1000, self.update_sensor_data)

    def repot_plant_action(self):
        # GEÄNDERT: Die Infobox wird sofort angezeigt, bevor der Thread startet
        messagebox.showinfo("Umgetopft", "Pflanze wurde umgetopft!\nSende Befehl zum Zurücksetzen des Gießzyklus...")
        threading.Thread(target=self._send_repot_reset_command, daemon=True).start()
        self.show_frame("main_menu")

    # GEÄNDERT: Sendet das Ergebnis an die Queue, statt eine Messagebox anzuzeigen
    def _send_repot_reset_command(self):
        if send_pump_command(action="repot_reset"):
            # Lege eine Erfolgs-Nachricht in die Queue
            self.queue.put(('info', 'Umgetopft', 'Gießzyklus-Reset-Befehl gesendet und verarbeitet.'))
        else:
            # Lege eine Fehler-Nachricht in die Queue
            self.queue.put(('error', 'Fehler', 'Fehler beim Senden oder Verarbeiten des Umtopf-Reset-Befehls.'))

    # GEÄNDERT: Die Logik wurde angepasst
    def trigger_manual_watering(self, amount_ml=None):
        water_amount = 0
        if amount_ml is None:
            custom_amount = simpledialog.askinteger("Manuelle Bewässerung",
                                                    "Wie viele ml sollen gegossen werden?",
                                                    parent=self, minvalue=10, maxvalue=500)
            if custom_amount is not None: water_amount = custom_amount
            else: return
        else:
            water_amount = amount_ml

        if water_amount > 0:
            # Zeige die Infobox sofort an, nicht im Thread
            messagebox.showinfo("Befehl wird gesendet", f"Sende Befehl, {water_amount} ml zu gießen...", parent=self)
            threading.Thread(target=self._send_manual_pump_command, args=(water_amount,), daemon=True).start()

    # GEÄNDERT: Sendet das Ergebnis an die Queue, statt eine Messagebox anzuzeigen
    def _send_manual_pump_command(self, amount_ml):
        if send_pump_command(amount_ml=amount_ml, action="pump_manual"):
            # Lege eine Erfolgs-Nachricht in die Queue
            self.queue.put(('info', 'Erfolg', f'{amount_ml} ml wurden gegossen.'))
        else:
            # Lege eine Fehler-Nachricht in die Queue
            self.queue.put(('error', 'Fehler', 'Pumpenbefehl konnte nicht verarbeitet werden (Timeout).'))

    def exit_program(self):
        # ... (unverändert)
        if messagebox.askyesno("Beenden", "Möchten Sie das Programm wirklich beenden?"):
            self.destroy()

    def reset_idle_timer(self, event=None):
        # ... (unverändert)
        if self.idle_timer_id: self.after_cancel(self.idle_timer_id)
        if self.current_frame == self.frames["idle_screen"] and event is not None:
            self.show_frame("main_menu")
        self.idle_timer_id = self.after(self.IDLE_TIMEOUT_MS, self.go_to_idle_screen)

    def go_to_idle_screen(self):
        # ... (unverändert)
        self.show_frame("idle_screen")

# --- (Der Rest der Datei, alle Frame-Klassen und der __main__ Block, bleibt unverändert) ---
# --- (BaseMenuFrame, MainMenuFrame, WateringSettingsFrame, SettingEditorFrame, etc...) ---
# --- Sie können den Rest des Codes von Ihrer ursprünglichen Datei kopieren ---
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
        tk.Button(self, text="2. Manuelle Bewässerung", command=lambda: self.controller.show_frame("manual_watering"), **button_style).pack(pady=10)
        tk.Button(self, text="3. Ich habe umgetopft!", command=lambda: self.controller.show_frame("confirm_repot"), **button_style).pack(pady=10)
        tk.Button(self, text="4. Programm beenden", command=self.controller.exit_program, **button_style).pack(pady=10)
        tk.Button(self, text="5. Zum Idle-Screen", command=lambda: self.controller.show_frame("idle_screen"), **button_style).pack(pady=10)

#...(Hier den Rest Ihrer Frame-Klassen einfügen, sie benötigen keine Änderungen)
#...
#...

if __name__ == "__main__":
    load_config()
    ads1115 = ADS1115()
    precheck = PreWateringCheck(ads1115)
    app = PlantWateringApp(ads1115, precheck)
    try:
        app.mainloop()
    except Exception as e:
        print(f"\nEin Fehler ist während der Ausführung aufgetreten: {e}")
        import traceback
        traceback.print_exc()
    finally:
        GPIO.cleanup()
        print("GPIO-Bereinigung abgeschlossen. Programm beendet.")