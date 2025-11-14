import time
from flask import Blueprint, request, jsonify

import state  # <--- zamiast "from state import registered_devices, ..."

devices_bp = Blueprint("devices", __name__)


# -------------------------------------------
# /handshake - test połączenia
# -------------------------------------------
@devices_bp.route("/handshake", methods=["POST"])
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
@devices_bp.route("/provision", methods=["POST"])
def provision():
    data = request.get_json(silent=True) or {}
    device_id = data.get("deviceId", f"unknown-{int(time.time())}")

    # IP: z JSON-a albo z request.remote_addr
    ip = data.get("ip") or request.remote_addr

    # wszystko przez touch_device, żeby było spójne z telemetry/pump
    state.touch_device(
        device_id=device_id,
        device_type=data.get("deviceType", "unknown"),
        device_name=data.get("deviceName", "unknown"),
        farm_id=data.get("farmId", "default"),
        ip=ip,
    )

    print(f"[PROVISION] {device_id} zarejestrowano z IP {ip}")
    return jsonify({"status": "stored", "deviceId": device_id}), 200


# -------------------------------------------
# /devices - lista zarejestrowanych urządzeń
# -------------------------------------------
@devices_bp.route("/devices", methods=["GET"])
def list_devices():
    """
    Zwraca WSZYSTKIE urządzenia zarejestrowane w registered_devices.json,
    razem z polami:
      - deviceId, deviceName, deviceType, farmId, ip
      - lastSeen
      - lastSeenAgeSec
      - online
    """
    # przelicz online / lastSeenAgeSec na podstawie lastSeen
    state.refresh_devices_online_flags(timeout_sec=700.0)

    # registered_devices teraz zawsze to, co w state (bez rozjazdu referencji)
    return jsonify(state.registered_devices), 200
