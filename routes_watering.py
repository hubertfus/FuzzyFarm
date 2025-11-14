import os
from flask import Blueprint, request, jsonify

from config import *
from tsk_logic import kalibruj_kontroler_z_danych, TSKWateringController
from state import DATA_DIR

watering_bp = Blueprint("watering", __name__)


# -------------------------------------------
# --- WATERING DECISION (podlewanie) ---
# -------------------------------------------
@watering_bp.route("/decision/<device_id>", methods=["POST"])
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
