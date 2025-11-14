from flask import Blueprint, request, jsonify

from state import read_logs

logs_bp = Blueprint("logs", __name__)


@logs_bp.route("/logs", methods=["GET"])
def get_all_logs():
    """
    GET /logs
    Opcjonalne query:
      ?deviceId=...   -> filtr po urządzeniu
      ?limit=200      -> maks. liczba rekordów (najnowsze)
    """
    device_id = request.args.get("deviceId")
    try:
        limit = int(request.args.get("limit", 500))
    except (TypeError, ValueError):
        limit = 500

    logs = read_logs(device_id=device_id, limit=limit)
    return jsonify({
        "deviceId": device_id,
        "count": len(logs),
        "logs": logs,
    }), 200


@logs_bp.route("/logs/<device_id>", methods=["GET"])
def get_logs_for_device(device_id):
    """
    GET /logs/<device_id>
    Opcjonalne query:
      ?limit=200
    """
    try:
        limit = int(request.args.get("limit", 500))
    except (TypeError, ValueError):
        limit = 500

    logs = read_logs(device_id=device_id, limit=limit)
    return jsonify({
        "deviceId": device_id,
        "count": len(logs),
        "logs": logs,
    }), 200
