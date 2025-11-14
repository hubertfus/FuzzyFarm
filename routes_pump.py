# ==============================================
#  routes_pump.py
#
#  Endpointy do sterowania pompkami (PUMP CONTROLLER).
#
#  Protokół z Pico:
#  -----------------
#  Pico (POST /pump/heartbeat) wysyła JSON:
#  {
#    "deviceId": "PICO-....-pump",
#    "deviceType": "pump-controller",
#    "deviceName": "PumpCtrl-1",
#    "farmId": "rack-1",
#    "pumping1": true/false,
#    "secondsLeft1": int,
#    "pumping2": true/false,
#    "secondsLeft2": int,
#    "queueLength": int,
#    "completed": [
#      { "pump": 1, "seconds": 2 },
#      { "pump": 2, "seconds": 2 }
#    ]
#  }
#
#  Serwer odpowiada:
#  ------------------
#  Nowy format z kolejką:
#  {
#    "queue": [
#      { "pump": 1, "seconds": N1 },
#      { "pump": 2, "seconds": N2 }
#    ]
#  }
#
#  Logika (nowa wersja):
#  ----------------------
#  - Stan per PUMP–Pico trzymamy w _device_state:
#      * has_pending   -> czy wysłaliśmy już podlewanie, na które czekamy
#      * last_water_ts -> kiedy ostatnio zakończono podlewanie
#  - Stan wilgotności per roślina trzymamy w telemetry_store (state.py),
#    a mapowanie soil -> roślina -> pompka w farm_layout.py.
#  - TSKWateringController z tsk_logic.py liczy, ile sekund podlewać
#    na podstawie soil_raw.
#  - Wynik to kolejka:
#      [ {"pump": X, "seconds": S}, ... ]
# ==============================================

from flask import Blueprint, request, jsonify
import time

from tsk_logic import TSKWateringController
from farm_layout import get_pump_for_plant
from state import telemetry_store, touch_device, append_log   # <--- DODANE append_log

pump_bp = Blueprint("pump", __name__, url_prefix="/pump")

# ======= KONFIG TSK / KALIBRACJA =======
# To są domyślne wartości – DOSTOSUJ pod swoje odczyty:
#
#  - SOIL_RAW_AIR    -> odczyt, gdy czujnik w powietrzu (sucho 0%)
#  - SOIL_RAW_WATER  -> odczyt, gdy czujnik w wodzie (mokro 100%)
#
#  - TSK_TIME_DRY    -> ile sekund podlewać, gdy "sucho"
#  - TSK_TIME_DAMP   -> ile sekund, gdy "w miarę"
#  - TSK_TIME_WET    -> ile sekund, gdy "mokro" (zwykle 0)
#
SOIL_RAW_AIR = 60000
SOIL_RAW_WATER = 20000

TSK_TIME_DRY = 10.0     # np. 10s przy bardzo suchej glebie
TSK_TIME_DAMP = 4.0     # np. 4s przy średniej wilgotności
TSK_TIME_WET = 0.0      # przy mokrej glebie nie podlewamy

# Minimalny odstęp między kolejnymi podlewaniami
MIN_INTERVAL = 60  # sekund – możesz zmienić np. na 300

# ======= STAN PUMP–PICO =======
# _device_state[device_id] = {
#   "has_pending": bool,
#   "last_water_ts": float
# }
_device_state = {}

# Cache kontrolerów TSK per plantId
_tsk_per_plant = {}


def get_tsk_for_plant(plant_id: str) -> TSKWateringController:
    """
    Dla uproszczenia wszystkie rośliny używają tych samych progów TSK.
    Jeśli chcesz, można potem zrobić osobne ustawienia per plant.
    """
    ctrl = _tsk_per_plant.get(plant_id)
    if ctrl is None:
        ctrl = TSKWateringController(
            val_in_air=SOIL_RAW_AIR,
            val_in_water=SOIL_RAW_WATER,
            time_dry=TSK_TIME_DRY,
            time_damp=TSK_TIME_DAMP,
            time_wet=TSK_TIME_WET,
        )
        _tsk_per_plant[plant_id] = ctrl
    return ctrl


@pump_bp.route("/heartbeat", methods=["POST"])
def pump_heartbeat():
    """
    Główny endpoint heartbeat dla PUMP CONTROLLER.

    Pico pyta:
      - co mam teraz podlewać?

    Serwer:
      - rejestruje / odświeża urządzenie (registered_devices)
      - aktualizuje stan (czy coś zostało zakończone),
      - sprawdza, czy minął minimalny odstęp między podlewaniami,
      - na podstawie telemetry_store + TSK liczy czasy podlewania
        per roślina, mapuje na pompki i zwraca kolejkę.
    """

    data = request.get_json(silent=True) or {}

    device_id   = data.get("deviceId", "unknown")
    device_type = data.get("deviceType", "pump-controller")
    device_name = data.get("deviceName", "PumpCtrl")
    farm_id     = data.get("farmId", "rack-1")

    pumping1   = data.get("pumping1", False)
    pumping2   = data.get("pumping2", False)
    queue_len  = data.get("queueLength", 0)
    completed  = data.get("completed", []) or []

    # === rejestr/odświeżenie urządzenia (żeby /devices je widziało) ===
    # ip bierzemy z request.remote_addr – to realne IP pompy
    touch_device(
        device_id=device_id,
        device_type=device_type,
        device_name=device_name,
        farm_id=farm_id,
        ip=request.remote_addr
    )

    st = _device_state.get(device_id)
    if st is None:
        st = {
            "has_pending": False,
            "last_water_ts": 0.0,
        }
        _device_state[device_id] = st

    print("========== /pump/heartbeat ==========")
    print(f"[PUMP HEARTBEAT] dev={device_id} farm={farm_id}")
    print("   pumping1:", pumping1,
          "pumping2:", pumping2,
          "queue_len:", queue_len,
          "completed:", completed)
    print("   state:", st)

    # 1) Obsługa zakończonych podlewań
    if completed:
        st["has_pending"] = False
        st["last_water_ts"] = time.time()
        print("[PUMP] Zakończone podlewanie:", completed)

        # LOG: zakończone podlewanie
        append_log(
            device_id=device_id,
            event_type="pump-completed",
            payload={
                "farmId": farm_id,
                "completed": completed
            }
        )

        # TODO: tutaj możesz:
        #  - dopisać log do CSV
        #  - zaktualizować statystyki farmy
        #  - zapisać info, która pompka ile sekund

    # 2) Jeśli wciąż mamy "pending", nie wysyłamy nowej kolejki
    if st["has_pending"]:
        print("[PUMP] Wciąż pending -> nie wysyłam nowej kolejki")
        return jsonify({"queue": []})

    # 3) Ograniczenie częstotliwości
    now = time.time()
    if now - st["last_water_ts"] < MIN_INTERVAL:
        print("[PUMP] Za wcześnie na nowe podlewanie "
              f"(min odstęp {MIN_INTERVAL}s, minie za {int(MIN_INTERVAL - (now - st['last_water_ts']))}s)")
        return jsonify({"queue": []})

    # 4) Logika TSK na podstawie telemetry_store
    farm_data = telemetry_store.get(farm_id, {})
    if not farm_data:
        print("[PUMP] Brak danych telemetrycznych (soil) dla farmy", farm_id)
        return jsonify({"queue": []})

    queue = []

    for plant_id, plant_data in farm_data.items():
        soil_raw = plant_data.get("soil_raw")
        if soil_raw is None:
            continue

        tsk = get_tsk_for_plant(plant_id)
        seconds = tsk.get_watering_time(soil_raw)

        # Zaokrąglamy do najbliższej sekundy
        seconds_int = int(round(seconds))
        if seconds_int <= 0:
            print(f"[PUMP][TSK] plant={plant_id} raw={soil_raw} -> {seconds:.2f}s -> pomijam (0s)")
            continue

        pump_no = get_pump_for_plant(farm_id, plant_id)
        if pump_no is None:
            print(f"[PUMP] Brak mapowania pompki dla plantId={plant_id} na farmie {farm_id}")
            continue

        print(f"[PUMP][TSK] plant={plant_id} raw={soil_raw} -> {seconds:.2f}s -> pump={pump_no}")
        queue.append({
            "pump": pump_no,
            "seconds": seconds_int
        })

    if not queue:
        print("[PUMP] TSK: żadna roślina nie wymaga podlewania")
        return jsonify({"queue": []})

    # 5) Ustawiamy pending i wysyłamy kolejkę
    st["has_pending"] = True
    print("[PUMP] Wysyłam nowe podlewanie (TSK):", queue)

    # LOG: nowa kolejka podlewania
    append_log(
        device_id=device_id,
        event_type="pump-queue-sent",
        payload={
            "farmId": farm_id,
            "queue": queue
        }
    )

    return jsonify({"queue": queue})
