import os
import json
import csv
import time
from datetime import datetime

# katalog na dane
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# PLIK Z LOGAMI ZDARZEŃ
LOGS_FILE = os.path.join(DATA_DIR, "events.log")

# rejestr urządzeń i dane telemetryczne w pamięci
registered_devices = {}
telemetry_store = {}

# ostatni lux per farma do sterowania światłem
env_last_by_farm = {}           # farmId -> {"lux": float, "ts": float}

# cele oświetlenia per farma
light_target_by_farm = {}       # farmId -> targetLux
DEFAULT_TARGET_LUX = 500        # domyślny cel dla nowych farm

# override lampy per farma (dla apki i logiki światła)
# farmId -> {"override": bool, "power": bool, "updatedTs": float}
light_override_by_farm = {}

# PLIK Z ZAREJESTROWANYMI URZĄDZENIAMI
DEVICES_FILE = os.path.join(DATA_DIR, "registered_devices.json")


def load_registered_devices():
    """Wczytuje registered_devices z pliku JSON."""
    global registered_devices
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE, "r") as f:
                registered_devices = json.load(f)
            print(f"[BOOT] Wczytano {len(registered_devices)} urządzeń z {DEVICES_FILE}")
        except Exception as e:
            print("[BOOT] Błąd wczytywania registered_devices:", e)
    else:
        print(f"[BOOT] Brak {DEVICES_FILE}, startuję pusty rejestr urządzeń")


def save_registered_devices():
    """Zapisuje registered_devices do pliku JSON."""
    try:
        with open(DEVICES_FILE, "w") as f:
            json.dump(registered_devices, f, indent=2)
        # print(f"[SAVE] registered_devices zapisane do {DEVICES_FILE}")
    except Exception as e:
        print("[SAVE] Błąd zapisu registered_devices:", e)


def touch_device(device_id: str,
                 device_type: str | None = None,
                 device_name: str | None = None,
                 farm_id: str | None = None,
                 ip: str | None = None):
    """
    Aktualizuje/zakłada wpis urządzenia:
      - lastSeen = teraz
      - lastSeenAgeSec = 0
      - online = True
    """
    if not device_id:
        return

    now = time.time()
    dev = registered_devices.get(device_id, {})

    dev["deviceId"] = device_id

    if device_type is not None:
        dev["deviceType"] = device_type
    if device_name is not None:
        dev["deviceName"] = device_name
    if farm_id is not None:
        dev["farmId"] = farm_id
    if ip is not None:
        dev["ip"] = ip

    dev["lastSeen"] = now
    dev["lastSeenAgeSec"] = 0.0
    dev["online"] = True

    registered_devices[device_id] = dev
    save_registered_devices()


def refresh_devices_online_flags(timeout_sec: float = 700.0):
    """
    Możesz to wołać np. w /devices:
      - aktualizuje lastSeenAgeSec
      - ustawia online=False, jeśli urządzenie nie meldowało się
        dłużej niż timeout_sec
    """
    now = time.time()
    changed = False

    for dev in registered_devices.values():
        last_seen = dev.get("lastSeen")
        if last_seen is None:
            continue
        age = now - last_seen
        dev["lastSeenAgeSec"] = age
        was_online = dev.get("online", False)
        is_online = age <= timeout_sec
        dev["online"] = is_online
        if is_online != was_online:
            changed = True

    if changed:
        save_registered_devices()


def write_csv_line(filename, header, row):
    """Pomocniczy zapis pojedynczej linii CSV (z nagłówkiem przy pierwszym zapisie)."""
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(header)
        writer.writerow(row)


def save_telemetry_to_csv(device_id, data):
    """Zapis telemetry do odpowiednich plików CSV w zależności od typu urządzenia."""
    timestamp_dt = datetime.now()
    device_type = data.get("deviceType", "unknown")
    timestamp_str = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')

    if device_type == "env-sensor":
        env = data.get("env", {})
        for key in ["tempC", "humRH", "lux"]:
            value = env.get(key)
            if value is None:
                continue
            filename = os.path.join(DATA_DIR, f"{device_id}_{key}.csv")
            write_csv_line(filename, ["timestamp", "value"], [timestamp_str, value])

            # przy lux możemy od razu ustawiać env_last_by_farm
            if key == "lux":
                farm_id = data.get("farmId", "rack-1")
                env_last_by_farm[farm_id] = {
                    "lux": float(value),
                    "ts": time.time(),
                }

    elif device_type == "soil-sensor":
        soil = data.get("soil", {})
        raw_value = soil.get("raw")
        if raw_value is not None:
            filename = os.path.join(DATA_DIR, f"{device_id}_soil_raw.csv")
            write_csv_line(filename, ["timestamp", "raw"], [timestamp_str, raw_value])

    else:
        filename = os.path.join(DATA_DIR, f"{device_id}_misc.csv")
        write_csv_line(filename, ["timestamp", "payload"], [timestamp_str, json.dumps(data)])


# --------- OVERRIDE ŚWIATŁA (apka / heartbeat) ---------


def get_light_override(farm_id: str):
    """
    Zwraca stan override lampy dla danej farmy:
      {
        "override": bool,
        "power": bool,
        "updatedTs": float
      }
    """
    return light_override_by_farm.get(farm_id, {
        "override": False,
        "power": False,
        "updatedTs": None,
    })


def set_light_override(farm_id: str, override=None, power=None):
    """
    Ustawia override/power dla lampy danej farmy.
    """
    state = light_override_by_farm.get(farm_id) or {
        "override": False,
        "power": False,
        "updatedTs": None,
    }

    if override is not None:
        state["override"] = bool(override)
    if power is not None:
        state["power"] = bool(power)

    state["updatedTs"] = datetime.now().timestamp()
    light_override_by_farm[farm_id] = state
    return state


# --------- LOGI ZDARZEŃ (TU SIĘ W KOŃCU ZAPISUJE DO PLIKU) ---------


def append_log(device_id: str | None,
               event_type: str,
               payload: dict | None = None):
    """
    Dopisuje wpis do pliku logów (JSONL) data/events.log.

    Każda linia:
    {
      "ts": "2025-11-14T21:37:00",
      "deviceId": "PICO-...",
      "event": "nazwa",
      "payload": {...}
    }
    """
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "deviceId": device_id,
        "event": event_type,
        "payload": payload or {},
    }
    print("[Log Zapisany]")
    try:
        with open(LOGS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print("[LOG] Błąd zapisu loga:", e)


def read_logs(device_id: str | None = None,
              event: str | None = None,
              limit: int = 500):
    """
    Prosty odczyt logów (na przyszły endpoint /logs).
    """
    if not os.path.exists(LOGS_FILE):
        return []

    rows = []
    try:
        with open(LOGS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if device_id is not None and obj.get("deviceId") != device_id:
                    continue
                if event is not None and obj.get("event") != event:
                    continue

                rows.append(obj)
    except Exception as e:
        print("[LOG] Błąd odczytu logów:", e)
        return []

    if len(rows) > limit:
        rows = rows[-limit:]

    return rows


# ====== AUTO-LOAD URZĄDZEŃ PRZY STARCIU ======
load_registered_devices()
