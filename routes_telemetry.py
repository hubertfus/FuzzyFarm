from datetime import time
import time as _time

from flask import Blueprint, request, jsonify

from farm_layout import get_plant_by_soil_device
from state import telemetry_store, touch_device, save_telemetry_to_csv

telemetry_bp = Blueprint("telemetry", __name__)


@telemetry_bp.route("/telemetry", methods=["POST"])
def telemetry():
    """
    Odbiera dane z Pico:
      - soil-sensor
      - env-sensor
      - dowolne urządzenia, które wysyłają /telemetry

    Robi:
      - aktualizuje registered_devices (touch_device)
      - zapisuje CSV (save_telemetry_to_csv)
      - zapisuje do telemetry_store (NOWE: ENV zapisujemy w tym samym formacie co soil)
    """
    data = request.get_json(silent=True) or {}

    device_id   = data.get("deviceId")
    device_type = data.get("deviceType")
    device_name = data.get("deviceName")
    farm_id     = data.get("farmId", "rack-1")
    ts          = data.get("ts")

    print("[TELEMETRY RAW]", data)

    # ===============================
    # Rejestracja / aktualizacja urządzenia
    # ===============================
    touch_device(
        device_id=device_id,
        device_type=device_type,
        device_name=device_name,
        farm_id=farm_id,
        ip=None,
    )

    # ===============================
    # Zapis CSV
    # ===============================
    if device_id:
        save_telemetry_to_csv(device_id, data)

    # ===============================
    # SOIL-SENSOR
    # ===============================
    if device_type == "soil-sensor":
        soil = data.get("soil", {})
        soil_raw = soil.get("raw")
        if soil_raw is None:
            return jsonify({"status": "error", "reason": "no soil.raw"}), 400

        # np. "PICO-e66xxx-soil" → obcinamy "-soil"
        base_device_id = device_id
        if base_device_id and base_device_id.endswith("-soil"):
            base_device_id = base_device_id[:-5]

        plant_info = get_plant_by_soil_device(farm_id, base_device_id)
        if not plant_info:
            print(f"[TELEMETRY] Nie znam soilDeviceId={base_device_id} na farmie {farm_id}")
        else:
            plant_id = plant_info["plantId"]
            print(
                f"[TELEMETRY] SOIL plant={plant_id} pump={plant_info['pump']} raw={soil_raw}"
            )

            farm_store = telemetry_store.setdefault(farm_id, {})
            farm_store[plant_id] = {
                "soil_raw": soil_raw,
                "ts": ts,
            }

    # ===============================
    # ENV-SENSOR *** FIX ***
    # ===============================
    if device_type == "env-sensor":
        env = data.get("env", {})
        if not env:
            return jsonify({"status": "error", "reason": "env missing"}), 400

        # klucz — ZAPISUJEMY W TYM SAMYM FORMACIE,
        # jaki oczekuje get_latest_env_for_farm()
        telemetry_store[device_id] = {
            "deviceId": device_id,
            "deviceType": "env-sensor",
            "farmId": farm_id,
            "payload": data,           # <--- pełne dane ENV
            "timestamp": _time.time(), # <- absolutnie kluczowe
        }

        print(f"[TELEMETRY] ENV zapisano OK {env}")

    return jsonify({"status": "ok"})


# -------------------------------------------
# /telemetry/<device_id>
# -------------------------------------------
@telemetry_bp.route("/telemetry/<device_id>", methods=["GET"])
def get_device_telemetry(device_id):
    entry = telemetry_store.get(device_id)
    if not entry:
        return jsonify({"status": "not found"}), 404
    return jsonify(entry), 200


# -------------------------------------------
# /farm/<farm_id>/status
# -------------------------------------------
@telemetry_bp.route("/farm/<farm_id>/status", methods=["GET"])
def farm_status(farm_id):
    """
    Szybki status farmy:
      - ostatni env-sensor (temp/hum/lux)
      - ostatni soil-sensor (raw)
    """
    now_ts = _time.time()

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
