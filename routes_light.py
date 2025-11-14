from datetime import datetime
import time
from flask import Blueprint, request, jsonify

from state import (
    env_last_by_farm,
    light_target_by_farm,
    registered_devices,
    save_registered_devices,
    DEFAULT_TARGET_LUX,
    get_light_override,
    append_log,   # <-- DODANE
)

light_bp = Blueprint("light", __name__)

MIN_LUX, MAX_LUX = 0, 2000      # clamp pomocniczy

# parametry lampy
PHASE_STEPS = 18          # 0..17
BRIGHTNESS_MAX = 9        # 0..9, 0 = najjaśniej, 9 = najciemniej

# Powyżej tego lux -> lampę wyłączamy (tylko próg, BEZ godzin)
LUX_OFF_THRESHOLD = 700

# -------------------------------------------
#  STARTUP RESET:
# -------------------------------------------
light_startup_done = set()


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
# --- LIGHT: HEARTBEAT (sterowanie lampą) ---
# -------------------------------------------
@light_bp.route("/light/heartbeat", methods=["POST"])
def light_heartbeat():
    """
    Body od Pico (light-controller):
    {
      "deviceId": "...",
      "deviceType": "light-controller",
      "farmId": "rack-1",
      "level": 0..17,
      "lampOn": true/false
    }
    """

    data = request.get_json(silent=True) or {}
    farm_id = data.get("farmId", "default")

    # --- rejestracja / odświeżenie light-controllera ---
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

    # UWAGA: "level" = faza 0..17
    cur_phase = int(data.get("level", 0)) % PHASE_STEPS
    lamp_on = bool(data.get("lampOn", False))

    # -------------------------------------------
    #  STARTUP RESET PER DEVICE
    # -------------------------------------------
    global light_startup_done
    if device_id and device_id not in light_startup_done:
        light_startup_done.add(device_id)

        clicks_to_zero = (-cur_phase) % PHASE_STEPS

        # LOG: startup reset
        append_log(
            device_id=device_id,
            event_type="light-startup-reset",
            payload={
                "farmId": farm_id,
                "curPhase": cur_phase,
                "clicksToZero": clicks_to_zero,
            }
        )

        return jsonify({
            "clicks": int(clicks_to_zero),
            "power": 1,   # wymuś ON przy starcie
            "info": {
                "reason": "startup-reset",
                "farmId": farm_id,
                "bootPhase": cur_phase,
                "targetPhase": 0,
            }
        }), 200

    # --- NORMALNA LOGIKA: oparta o lux + override ---

    # aktualne pomiary ENV dla farmy
    env = env_last_by_farm.get(farm_id)
    if not env:
        # LOG: brak lux
        append_log(
            device_id=device_id,
            event_type="light-no-lux",
            payload={
                "farmId": farm_id,
                "lampOn": lamp_on,
            }
        )

        # brak lux -> nic nie ruszamy, zostawiamy jak jest
        return jsonify({
            "clicks": 0,
            "power": int(lamp_on),
            "info": {
                "reason": "no lux for farm",
                "farmId": farm_id
            }
        }), 200

    lux = max(MIN_LUX, min(MAX_LUX, float(env["lux"])))

    # docelowy poziom lux dla farmy (z /light/target, albo domyślny)
    target_lux = float(light_target_by_farm.get(farm_id, DEFAULT_TARGET_LUX))

    # --- AUTO ON/OFF TYLKO OD LUX (bez godzin) ---
    # Powyżej LUX_OFF_THRESHOLD zawsze OFF.
    desired_on = lux < LUX_OFF_THRESHOLD

    # --- mapowanie lux -> abstrakcyjna jasność 0..9 zależna od targetLux ---
    # 0 = max jasno, 9 = max ciemno
    if not desired_on:
        desired_brightness = BRIGHTNESS_MAX
        lux_ratio = lux / target_lux if target_lux > 0 else 1.0
    else:
        lux_ratio = lux / target_lux if target_lux > 0 else 1.0

        if lux_ratio < 0.4:
            desired_brightness = 0
        elif lux_ratio < 0.7:
            desired_brightness = 3
        elif lux_ratio < 1.0:
            desired_brightness = 5
        elif lux_ratio < 1.2:
            desired_brightness = 7
        else:
            desired_brightness = 9

    # --- OVERRIDE Z APLIKACJI ---
    override_state = get_light_override(farm_id)
    if override_state.get("override"):
        desired_on = bool(override_state.get("power"))

    # aktualna jasność z fazy
    cur_brightness = phase_to_brightness(cur_phase)

    if not desired_on:
        clicks = 0
        desired_phase = cur_phase
    else:
        desired_phase, clicks = choose_phase_for_brightness(
            cur_phase,
            desired_brightness
        )

    # LOG: decyzja światła (to jest „światło się zmieniło tak i tak”)
    append_log(
        device_id=device_id,
        event_type="light-decision",
        payload={
            "farmId": farm_id,
            "lux": lux,
            "targetLux": target_lux,
            "luxRatio": lux_ratio,
            "curPhase": cur_phase,
            "curBrightness": cur_brightness,
            "desiredBrightness": desired_brightness,
            "desiredPhase": desired_phase,
            "clicks": clicks,
            "desiredOn": desired_on,
            "override": override_state,
        }
    )

    return jsonify({
        "clicks": int(clicks),
        "power": 1 if desired_on else 0,
        "info": {
            "farmId": farm_id,
            "envLux": lux,
            "targetLux": int(target_lux),
            "luxRatio": lux_ratio,

            "offLuxThreshold": LUX_OFF_THRESHOLD,

            # DIAGNOSTYKA
            "curPhase": cur_phase,
            "curBrightness": cur_brightness,
            "desiredBrightness": int(desired_brightness),
            "desiredPhase": int(desired_phase),
            "override": override_state,
        }
    }), 200


# -------------------------------------------
# --- LIGHT: odczyt/zmiana targetLux per farma ---
# -------------------------------------------
@light_bp.route("/light/target", methods=["GET", "POST"])
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

    # LOG: zmiana targetLux
    append_log(
        device_id=None,
        event_type="light-target-changed",
        payload={
            "farmId": farm_id,
            "targetLux": target,
        }
    )

    return jsonify({"status": "ok", "farmId": farm_id, "targetLux": target}), 200
