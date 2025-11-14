from datetime import datetime
import json

from flask import Flask, request, jsonify
import time, os, csv

from config import *
from tsk_logic import kalibruj_kontroler_z_danych, TSKWateringController

app = Flask(__name__)

# rejestr urządzeń i dane telemetryczne w pamięci
registered_devices = {}
telemetry_store = {}

# ostatni lux per farma do sterowania światłem
env_last_by_farm = {}           # farmId -> {"lux": float, "ts": float}

# cele oświetlenia per farma (na razie nieużywane, ale zostawiam)
light_target_by_farm = {}       # farmId -> targetLux
DEFAULT_TARGET_LUX = 500        # domyślny cel dla nowych farm (tylko informacyjnie)

MIN_LUX, MAX_LUX = 0, 2000      # clamp pomocniczy

# NOWE: parametry lampy / dnia
N_LEVELS = 9                    # 0..8 – tyle poziomów jasności w lampie
DAY_START_H = 8                 # "dzień" od 8:00
DAY_END_H   = 22                # do 22:00
LUX_OFF_THRESHOLD = 700         # powyżej tego lux -> lampę wyłączamy

# katalog na dane
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PHASE_STEPS = 18          # 0..17
BRIGHTNESS_MAX = 9        # 0..9, 0 = najjaśniej, 9 = najciemniej

# ---- PLIK Z ZAREJESTROWANYMI URZĄDZENIAMI ----
DEVICES_FILE = os.path.join(DATA_DIR, "registered_devices.json")


def load_registered_devices():
    global registered_devices
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE, "r") as f:
                registered_devices = json.load(f)
            print(f"[BOOT] Wczytano {len(registered_devices)} urządzeń z {DEVICES_FILE}")
        except Exception as e:
            print("[BOOT] Błąd wczytywania registered_devices:", e)


def save_registered_devices():
    try:
        with open(DEVICES_FILE, "w") as f:
            json.dump(registered_devices, f, indent=2)
        print(f"[SAVE] registered_devices zapisane do {DEVICES_FILE}")
    except Exception as e:
        print("[SAVE] Błąd zapisu registered_devices:", e)


def phase_to_brightness(phase: int) -> int:
    """Mapuje fazę 0..17 na abstrakcyjną jasność 0..9 (0 = max jasno, 9 = max ciemno)."""
    phase = phase % PHASE_STEPS
    if phase <= BRIGHTNESS_MAX:
        return phase
    else:
        # prawa strona V, np. 10 -> 8, 17 -> 1
        return PHASE_STEPS - phase


def choose_phase_for_brightness(cur_phase: int, desired_brightness: int):
    """
    Mając aktualną fazę 0..17 i chcianą jasność 0..9,
    wybierz fazę (lewa/prawa gałąź V), do której dojdziemy
    najmniejszą liczbą klików DO PRZODU.
    Zwraca: (best_phase, clicks_forward)
    """
    cur_phase = cur_phase % PHASE_STEPS
    b = max(0, min(BRIGHTNESS_MAX, int(desired_brightness)))

    # lewa gałąź V
    left = b
    # prawa gałąź V (symetryczna)
    right = (PHASE_STEPS - b) % PHASE_STEPS

    candidates = [left]
    if right != left:
        candidates.append(right)

    best_phase = cur_phase
    best_dist = 0

    for p in candidates:
        dist = (p - cur_phase) % PHASE_STEPS  # tylko do przodu
        if best_phase == cur_phase and best_dist == 0:
            best_phase, best_dist = p, dist
        elif dist < best_dist:
            best_phase, best_dist = p, dist

    return best_phase, best_dist


# -------------------------------------------
# /handshake - test połączenia
# -------------------------------------------
@app.route("/handshake", methods=["POST"])
def handshake():
    data = request.get_json(silent=True) or {}
    client = data.get("client", "unknown")
    version = data.get("version", "0")

    return jsonify({
        "status": "ok",
        "server": "pico-provisioner",
        "protocol": 1,
        "echo_client": client,
        "echo_version": version
    }), 200


# -------------------------------------------
# /provision - rejestracja Pico po Wi-Fi
# -------------------------------------------
@app.route("/provision", methods=["POST"])
def provision():
    data = request.get_json(silent=True) or {}
    device_id = data.get("deviceId", f"unknown-{int(time.time())}")

    # IP: z JSON-a albo z request.remote_addr
    ip = data.get("ip") or request.remote_addr

    registered_devices[device_id] = {
        "deviceId": device_id,
        "deviceName": data.get("deviceName", "unknown"),
        "deviceType": data.get("deviceType", "unknown"),
        "farmId": data.get("farmId", "default"),
        "ip": ip,
        "lastSeen": time.time()
    }
    save_registered_devices()
    print(f"[PROVISION] {device_id} zarejestrowano z IP {ip}")
    return jsonify({"status": "stored", "deviceId": device_id}), 200


# -------------------------------------------
# /telemetry - odbiór pomiarów z Pico
# -------------------------------------------
@app.route("/telemetry", methods=["POST"])
def telemetry():
    data = request.get_json(silent=True) or {}
    print("[TELEMETRY RAW]", data)

    # próbujemy złapać deviceId z różnych pól
    device_id = (
        data.get("deviceId")
        or data.get("device_id")
        or data.get("id")
    )

    device_type = data.get("deviceType", "unknown")
    farm_id = data.get("farmId", "default")
    now_ts = time.time()

    # jeśli dalej nie ma deviceId -> zrób fallback
    if not device_id:
        # zgadnij typ: env / soil / unknown
        if "soil" in data:
            guessed_type = "soil-sensor"
        elif "env" in data:
            guessed_type = "env-sensor"
        else:
            guessed_type = device_type or "unknown"

        device_type = device_type or guessed_type

        ip_str = (request.remote_addr or "unknown").replace(".", "_")
        device_id = f"auto-{guessed_type}-{ip_str}"
        print(f"[TELEMETRY] Brak deviceId w payload, używam wygenerowanego: {device_id}")

    telemetry_store[device_id] = {
        "deviceId": device_id,
        "deviceType": device_type,
        "timestamp": now_ts,
        "payload": data
    }

    # Zapisz dane do CSV
    save_telemetry_to_csv(device_id, data)

    # Aktualizuj ostatni lux dla danej farmy (do sterowania światłem)
    if device_type == "env-sensor":
        env = data.get("env", {})
        lux = env.get("lux")
        if lux is not None:
            env_last_by_farm[farm_id] = {"lux": float(lux), "ts": now_ts}

        print(f"[ENV] {device_id} -> T={env.get('tempC')}°C RH={env.get('humRH')}% Lux={env.get('lux')}")
    elif device_type == "soil-sensor":
        soil = data.get("soil", {})
        print(f"[SOIL] {device_id} -> RAW={soil.get('raw')}")
    else:
        print(f"[TELEMETRY] {device_id}: {data}")

    # Aktualizacja / dopisanie urządzenia do registered_devices
    dev_rec = registered_devices.get(device_id)
    ip = data.get("ip") or request.remote_addr

    if dev_rec:
        dev_rec["lastSeen"] = now_ts
        if ip:
            dev_rec["ip"] = ip
        if device_type:
            dev_rec["deviceType"] = device_type
        if farm_id:
            dev_rec["farmId"] = farm_id
    else:
        registered_devices[device_id] = {
            "deviceId": device_id,
            "deviceName": data.get("deviceName", "unknown"),
            "deviceType": device_type,
            "farmId": farm_id,
            "ip": ip,
            "lastSeen": now_ts
        }

    save_registered_devices()
    return jsonify({"status": "ok"}), 200


# -------------------------------------------
# /devices - lista zarejestrowanych urządzeń
# -------------------------------------------
@app.route("/devices", methods=["GET"])
def list_devices():
    now_ts = time.time()
    result = {}
    for dev_id, info in registered_devices.items():
        last_seen = info.get("lastSeen")
        if last_seen:
            age = now_ts - last_seen
            online = age < 60  # online jeśli widziany w ciągu ostatnich 60s
        else:
            age = None
            online = False

        d = dict(info)  # kopia
        d["online"] = online
        d["lastSeenAgeSec"] = age
        result[dev_id] = d

    return jsonify(result), 200


# -------------------------------------------
# /telemetry/<device_id> - ostatni odczyt
# -------------------------------------------
@app.route("/telemetry/<device_id>", methods=["GET"])
def get_device_telemetry(device_id):
    entry = telemetry_store.get(device_id)
    if not entry:
        return jsonify({"status": "not found"}), 404
    return jsonify(entry), 200


# -------------------------------------------
# /farm/<farm_id>/status - skrót stanu farmy
# -------------------------------------------
@app.route("/farm/<farm_id>/status", methods=["GET"])
def farm_status(farm_id):
    """
    Zbiera szybki status farmy:
      - ostatni env-sensor (temp, hum, lux)
      - ostatni soil-sensor (raw)
    """
    now_ts = time.time()

    latest_env = None
    latest_env_ts = None
    latest_soil = None
    latest_soil_ts = None

    for dev_id, entry in telemetry_store.items():
        payload = entry.get("payload", {})
        dt = entry.get("deviceType", payload.get("deviceType", "unknown"))
        dev_farm = payload.get("farmId", "default")
        ts = entry.get("timestamp", 0)

        if dev_farm != farm_id:
            continue

        if dt == "env-sensor":
            if (latest_env_ts is None) or (ts > latest_env_ts):
                latest_env_ts = ts
                latest_env = payload.get("env", {})

        elif dt == "soil-sensor":
            if (latest_soil_ts is None) or (ts > latest_soil_ts):
                latest_soil_ts = ts
                latest_soil = payload.get("soil", {})

    resp = {
        "farmId": farm_id,
        "env": {
            "data": latest_env,
            "ts": latest_env_ts,
            "ageSec": (now_ts - latest_env_ts) if latest_env_ts else None
        },
        "soil": {
            "data": latest_soil,
            "ts": latest_soil_ts,
            "ageSec": (now_ts - latest_soil_ts) if latest_soil_ts else None
        }
    }
    return jsonify(resp), 200


# -------------------------------------------
# --- WATERING DECISION (podlewanie) ---
# -------------------------------------------
@app.route("/decision/<device_id>", methods=["POST"])
def get_watering_decision(device_id):
    """
    Pobiera aktualny odczyt 'raw' i zwraca obliczony czas lania wody
    dla konkretnego urządzenia, używając jego własnych danych historycznych
    do dynamicznej kalibracji.
    """
    data = request.get_json(silent=True)
    if not data or "raw" not in data:
        return jsonify({"status": "error", "reason": "Missing 'raw' value in JSON body"}), 400

    try:
        current_raw_value = int(data.get("raw"))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "reason": f"Invalid 'raw' value: {data.get('raw')}"}), 400

    history_csv_file = os.path.join(DATA_DIR, f"{device_id}_soil_raw.csv")

    CAL_DRY_AIR, CAL_WET_WATER = kalibruj_kontroler_z_danych(
        csv_file=history_csv_file,
        dni_wstecz=DNI_DO_ANALIZY,
        domyslny_sucho=DEFAULT_CAL_DRY_AIR,
        domyslny_mokro=DEFAULT_CAL_WET_WATER
    )

    try:
        kontroler = TSKWateringController(
            val_in_air=CAL_DRY_AIR,
            val_in_water=CAL_WET_WATER,
            time_dry=TIME_IF_DRY,
            time_damp=TIME_IF_DAMP,
            time_wet=TIME_IF_WET
        )
    except ValueError as e:
        print(f"Błąd inicjalizacji TSK: {e}")
        return jsonify({"status": "error", "reason": f"TSK Init Error: {e}"}), 500

    watering_time = kontroler.get_watering_time(current_raw_value)

    return jsonify({
        "status": "decision_calculated",
        "device_id": device_id,
        "current_raw_value": current_raw_value,
        "watering_time_sec": round(watering_time, 2),
        "calibration_used": {
            "dry_threshold": CAL_DRY_AIR,
            "wet_threshold": CAL_WET_WATER
        }
    }), 200


# -------------------------------------------
# --- LIGHT: HEARTBEAT (sterowanie lampą) ---
# -------------------------------------------
@app.route("/light/heartbeat", methods=["POST"])
def light_heartbeat():
    """
    Body od Pico (light-controller):
    {
      "deviceId": "...",
      "deviceType": "light-controller",
      "farmId": "rack-1",
      "level": 0..17,        # FAZA (ilość klików mod 18)
      "lampOn": true/false
    }

    Odpowiedź:
    {
      "clicks": <ile klików jasności do przodu wykonać (0..17)>,
      "power": 0/1,
      "info": { diagnostyka }
    }
    """

    data = request.get_json(silent=True) or {}
    farm_id = data.get("farmId", "default")

    # Rejestracja / odświeżenie light-controllera
    device_id = data.get("deviceId")
    device_type = data.get("deviceType", "light-controller")
    now_ts = time.time()
    ip = data.get("ip") or request.remote_addr

    if device_id:
        dev_rec = registered_devices.get(device_id)
        if dev_rec:
            dev_rec["lastSeen"] = now_ts
            if ip:
                dev_rec["ip"] = ip
        else:
            registered_devices[device_id] = {
                "deviceId": device_id,
                "deviceName": data.get("deviceName", "LightCtrl-1"),
                "deviceType": device_type,
                "farmId": farm_id,
                "ip": ip,
                "lastSeen": now_ts
            }
        save_registered_devices()

    # UWAGA: od teraz "level" = faza 0..17
    cur_phase = int(data.get("level", 0)) % PHASE_STEPS

    # aktualne pomiary ENV dla farmy
    env = env_last_by_farm.get(farm_id)
    if not env:
        return jsonify({
            "clicks": 0,
            "power": 0,
            "info": {"reason": "no lux for farm"}
        }), 200

    lux = max(MIN_LUX, min(MAX_LUX, env["lux"]))

    # czy jest "dzień"
    now = datetime.now()
    hour = now.hour
    in_day = DAY_START_H <= hour < DAY_END_H

    # ON/OFF
    if (not in_day) or (lux >= LUX_OFF_THRESHOLD):
        desired_on = False
    else:
        desired_on = True

    # --- mapowanie lux -> abstrakcyjna jasność 0..9 ---
    # 0 = max jasno, 9 = max ciemno
    if not desired_on:
        # lampa ma być wyłączona; nie ruszamy jasności (clicks = 0),
        # ale do diagnostyki policzymy sobie obecny "bright"
        desired_brightness = BRIGHTNESS_MAX  # np. "najciemniej"
    else:
        if lux < 100:
            desired_brightness = 0   # max doświetlanie gdy ciemno
        elif lux < 300:
            desired_brightness = 3
        elif lux < 500:
            desired_brightness = 5
        else:  # 500–LUX_OFF_THRESHOLD
            desired_brightness = 7

    # aktualna jasność z fazy
    cur_brightness = phase_to_brightness(cur_phase)

    if not desired_on:
        # jak lampa ma być OFF, nie klikamy nic – tylko power=0
        clicks = 0
        desired_phase = cur_phase
    else:
        # wybierz fazę odpowiadającą desired_brightness
        desired_phase, clicks = choose_phase_for_brightness(
            cur_phase,
            desired_brightness
        )

    return jsonify({
        "clicks": int(clicks),
        "power": 1 if desired_on else 0,
        "info": {
            "farmId": farm_id,
            "envLux": lux,
            "dayWindow": {
                "start": DAY_START_H,
                "end": DAY_END_H
            },
            "inDay": in_day,
            "offLuxThreshold": LUX_OFF_THRESHOLD,

            # DIAGNOSTYKA – żebyś widział co się dzieje
            "curPhase": cur_phase,
            "curBrightness": cur_brightness,
            "desiredBrightness": int(desired_brightness),
            "desiredPhase": int(desired_phase),
        }
    }), 200


# -------------------------------------------
# --- LIGHT: odczyt/zmiana targetLux per farma ---
# -------------------------------------------
@app.route("/light/target", methods=["GET", "POST"])
def light_target():
    """
    GET  /light/target?farmId=rack-1
      -> {farmId, targetLux}

    POST /light/target
      JSON: {farmId: "rack-1", targetLux: 650}
      -> zapisuje w pamięci (na razie bez pliku)
    """
    if request.method == "GET":
        farm_id = request.args.get("farmId", "default")
        target = light_target_by_farm.get(farm_id, DEFAULT_TARGET_LUX)
        return jsonify({"farmId": farm_id, "targetLux": target}), 200

    # POST
    data = request.get_json(silent=True) or {}
    farm_id = data.get("farmId", "default")
    try:
        target = int(data.get("targetLux"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "reason": "invalid targetLux"}), 400

    light_target_by_farm[farm_id] = target
    return jsonify({"status": "ok", "farmId": farm_id, "targetLux": target}), 200


# -------------------------------------------
# Funkcja: zapis do CSV (ZMODYFIKOWANA)
# -------------------------------------------
def save_telemetry_to_csv(device_id, data):
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

    elif device_type == "soil-sensor":
        soil = data.get("soil", {})
        raw_value = soil.get("raw")
        if raw_value is not None:
            filename = os.path.join(DATA_DIR, f"{device_id}_raw.csv")
            write_csv_line(filename, ["timestamp", "raw"], [timestamp_str, raw_value])

    else:
        filename = os.path.join(DATA_DIR, f"{device_id}_misc.csv")
        write_csv_line(filename, ["timestamp", "payload"], [timestamp_str, json.dumps(data)])


# -------------------------------------------
# Pomocnicza funkcja do zapisu CSV
# -------------------------------------------
def write_csv_line(filename, header, row):
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(header)
        writer.writerow(row)


# -------------------------------------------
# Start serwera
# -------------------------------------------
if __name__ == "__main__":
    load_registered_devices()
    app.run(host="0.0.0.0", port=8000, debug=True)
