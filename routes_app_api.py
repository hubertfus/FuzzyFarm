import os
import csv
import time
from flask import Blueprint, request, jsonify

from state import (
    DATA_DIR,
    telemetry_store,
    registered_devices,
    get_light_override,
    set_light_override,
)

app_api_bp = Blueprint("app_api", __name__)

# domyślna farma – możesz zmienić, jeśli używasz innej
DEFAULT_FARM_ID = "rack-1"


# -------------------------------------------
# Pomocnicze: przeliczanie RAW soil -> %
# -------------------------------------------
def raw_soil_to_pct(raw):
    """
    Bardzo prymitywne mapowanie RAW -> % wilgotności.
    Zakładamy:
      - ~60000 = totalnie sucho (0%)
      - ~20000 = bardzo mokro (100%)
    """
    if raw is None:
        return None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None

    dry = 60000
    wet = 20000
    if val < wet:
        val = wet
    if val > dry:
        val = dry

    pct = int((dry - val) * 100 / (dry - wet))
    if pct < 0:
        pct = 0
    if pct > 100:
        pct = 100
    return pct


# -------------------------------------------
# Pomocnicze: ostatni ENV-sensor dla farmy
# -------------------------------------------
def get_latest_env_for_farm(farm_id: str):
    """
    Szuka najświeższego odczytu z czujnika środowiskowego (env-sensor)
    dla podanej farmy na podstawie telemetry_store.

    Zwraca:
      {
        "deviceId": str,
        "data": { "tempC": ..., "humRH": ..., "lux": ... },
        "tsServer": float,   # kiedy serwer to dostał (time.time())
        "ageSec": float | None,
      }
    albo None, jeśli nic nie znaleziono.
    """
    latest_env = None
    latest_env_ts = None
    latest_env_device_id = None

    for dev_id, entry in telemetry_store.items():
        payload = entry.get("payload", {}) or {}
        device_type = entry.get("deviceType") or payload.get("deviceType", "unknown")
        dev_farm = payload.get("farmId", "default")
        ts_server = entry.get("timestamp", 0.0)

        if dev_farm != farm_id:
            continue

        if device_type == "env-sensor":
            if latest_env_ts is None or ts_server > latest_env_ts:
                latest_env_ts = ts_server
                latest_env = payload.get("env", {}) or {}
                latest_env_device_id = dev_id

    if latest_env is None:
        return None

    now_ts = time.time()
    age_sec = None
    if latest_env_ts:
        age_sec = now_ts - latest_env_ts

    return {
        "deviceId": latest_env_device_id,
        "data": latest_env,
        "tsServer": latest_env_ts,
        "ageSec": age_sec,
    }


# -------------------------------------------
# Pomocnicze: doniczki z plików *_soil_raw.csv
# -------------------------------------------
def read_pots_from_csv(farm_id: str):
    """
    Szuka plików:
        <deviceId>_soil_raw.csv
    w katalogu DATA_DIR i traktuje każdy taki plik jako doniczkę.

    Zwraca listę słowników:
      {
        "deviceId": "...",
        "id": "...",       # identyfikator doniczki (na razie = deviceId)
        "name": "...",     # nazwa doniczki (na razie = deviceId lub friendlyName)
        "raw": float | None,
        "timestamp": "YYYY-MM-DD HH:MM:SS" | None,
      }
    Filtrowane po farmie na podstawie registered_devices / telemetry_store,
    jeśli mamy taką informację.
    """
    pots = []

    if not os.path.isdir(DATA_DIR):
        return pots

    for filename in os.listdir(DATA_DIR):
        if not filename.endswith("_soil_raw.csv"):
            continue

        device_id = filename[:-len("_soil_raw.csv")]
        path = os.path.join(DATA_DIR, filename)

        # Ustalamy farmę, jeśli się da
        farm_for_device = None
        meta = registered_devices.get(device_id)
        if meta:
            farm_for_device = meta.get("farmId")

        if farm_for_device is None:
            entry = telemetry_store.get(device_id)
            if entry:
                payload = entry.get("payload", {}) or {}
                farm_for_device = payload.get("farmId")

        # jeśli znamy farmę i nie zgadza się z żądaną, pomijamy
        if farm_for_device is not None and farm_for_device != farm_id:
            continue

        last_ts = None
        last_raw = None

        try:
            with open(path, "r", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)  # ["timestamp","raw"]
                for row in reader:
                    if len(row) < 2:
                        continue
                    last_ts = row[0]
                    try:
                        last_raw = float(row[1])
                    except (TypeError, ValueError):
                        last_raw = None
        except Exception as e:
            print(f"[CSV] Błąd czytania {path}: {e}")
            continue

        # nazwa doniczki – na razie deviceId, albo friendlyName z registered_devices
        name = None
        if meta:
            name = meta.get("friendlyName") or meta.get("deviceName") or meta.get("name")
        if not name:
            name = device_id

        pots.append({
            "deviceId": device_id,
            "id": device_id,
            "name": name,
            "raw": last_raw,
            "timestamp": last_ts,
        })

    return pots


# -------------------------------------------
# /api/farm/summary - wszystko na HomeScreen
# -------------------------------------------
@app_api_bp.route("/api/farm/summary", methods=["GET"])
def farm_summary():
    """
    Zbiorcze dane do dashboardu w apce:
      - stan oświetlenia (override z apki)
      - ostatni czujnik środowiskowy (tempC, humRH, lux)
      - doniczki z plików *_soil_raw.csv (moisturePct z RAW)
    """
    farm_id = request.args.get("farmId") or DEFAULT_FARM_ID

    # ---- ENV SENSOR ----
    env_info = get_latest_env_for_farm(farm_id)
    if env_info is not None:
        env_block = {
            "deviceId": env_info["deviceId"],
            "data": env_info["data"],
            "ts": env_info["tsServer"],
            "ageSec": env_info["ageSec"],
        }
    else:
        env_block = None

    # ---- DONICZKI z CSV ----
    pots_csv = read_pots_from_csv(farm_id)
    pots = []
    for p in pots_csv:
        raw = p.get("raw")
        moisture_pct = raw_soil_to_pct(raw)
        pot = {
            "id": p.get("id"),
            "deviceId": p.get("deviceId"),
            "name": p.get("name"),
            "moisturePct": moisture_pct,
            "raw": raw,
            "ts": p.get("timestamp"),
        }
        pots.append(pot)

    # ---- STAN ŚWIATŁA (override) ----
    light_state = get_light_override(farm_id)

    return jsonify({
        "farmId": farm_id,
        "light": light_state,
        "envSensor": env_block,
        "pots": pots,
    }), 200


# -------------------------------------------
# /api/farm/env - tylko ENV (opcjonalne)
# -------------------------------------------
@app_api_bp.route("/api/farm/env", methods=["GET"])
def farm_env():
    farm_id = request.args.get("farmId") or DEFAULT_FARM_ID
    env_info = get_latest_env_for_farm(farm_id)
    if env_info is None:
        return jsonify({
            "farmId": farm_id,
            "env": None,
        }), 200

    env_data = env_info["data"]
    return jsonify({
        "farmId": farm_id,
        "env": {
            "deviceId": env_info["deviceId"],
            "tempC": env_data.get("tempC"),
            "humRH": env_data.get("humRH"),
            "lux": env_data.get("lux"),
            "tsServer": env_info["tsServer"],
            "ageSec": env_info["ageSec"],
        }
    }), 200


# -------------------------------------------
# /api/farm/light - sterowanie lampą z apki
# -------------------------------------------
@app_api_bp.route("/api/farm/light", methods=["GET", "POST"])
def farm_light():
    """
    GET  /api/farm/light?farmId=rack-1
      -> { farmId, override, power, updatedTs }

    POST /api/farm/light
      Body JSON:
        {
          "farmId": "rack-1",      # opcjonalnie
          "override": true/false,  # jeśli true -> wymuszamy power
          "power": true/false      # ON/OFF gdy override = true
        }

    Jeśli override=false -> wracamy do trybu AUTO.
    """
    if request.method == "GET":
        farm_id = request.args.get("farmId") or DEFAULT_FARM_ID
        state = get_light_override(farm_id)
        return jsonify({
            "farmId": farm_id,
            "override": state.get("override", False),
            "power": state.get("power", False),
            "updatedTs": state.get("updatedTs"),
        }), 200

    # POST
    body = request.get_json(silent=True) or {}
    farm_id = body.get("farmId") or DEFAULT_FARM_ID

    override = body.get("override")
    power = body.get("power")

    # jeśli klient poda tylko "power" bez override -> traktujemy to jako override=True
    if override is None and power is not None:
        override = True

    state = set_light_override(farm_id, override=override, power=power)

    return jsonify({
        "ok": True,
        "farmId": farm_id,
        "state": state
    }), 200

# -------------------------------------------
# Historia wilgotności dla doniczki (z CSV)
# -------------------------------------------
def read_pot_history(pot_id: str, limit: int = 200):
    """
    Czyta historię z pliku:
        data/<pot_id>_soil_raw.csv

    Format CSV: timestamp,raw

    Zwraca listę:
      [
        { "ts": "2025-11-14 02:00:01", "raw": 24550.0, "moisturePct": 62 },
        ...
      ]
    (max `limit` najnowszych punktów)
    """
    path = os.path.join(DATA_DIR, f"{pot_id}_soil_raw.csv")
    if not os.path.exists(path):
        return []

    rows = []
    try:
        with open(path, "r", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)  # ["timestamp","raw"]
            for row in reader:
                if len(row) < 2:
                    continue
                ts = row[0]
                try:
                    raw = float(row[1])
                except (TypeError, ValueError):
                    raw = None
                rows.append((ts, raw))
    except Exception as e:
        print(f"[CSV] Błąd czytania historii {path}: {e}")
        return []

    # bierzemy tylko ostatnie `limit` punktów
    if len(rows) > limit:
        rows = rows[-limit:]

    points = []
    for ts, raw in rows:
        moisture = raw_soil_to_pct(raw)
        points.append({
            "ts": ts,
            "raw": raw,
            "moisturePct": moisture,
        })

    return points


@app_api_bp.route("/api/pots/history", methods=["GET"])
def pot_history():
    """
    GET /api/pots/history?potId=<ID>&limit=200

    potId = to samo id, które masz w polu "id" w /api/farm/summary (czyli deviceId od soil-sensora).

    Odpowiedź:
      {
        "potId": "...",
        "points": [
          { "ts": "...", "raw": 24550.0, "moisturePct": 62 },
          ...
        ]
      }
    """
    pot_id = request.args.get("potId")
    if not pot_id:
        return jsonify({"error": "potId is required"}), 400

    try:
        limit = int(request.args.get("limit", "200"))
    except ValueError:
        limit = 200

    limit = max(10, min(1000, limit))  # trochę sanity check

    points = read_pot_history(pot_id, limit=limit)

    return jsonify({
        "potId": pot_id,
        "points": points
    }), 200
