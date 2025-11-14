from flask import Flask

from state import load_registered_devices
from routes_devices import devices_bp
from routes_telemetry import telemetry_bp
from routes_light import light_bp
from routes_watering import watering_bp
from routes_app_api import app_api_bp
from routes_logs import logs_bp

# Z routes_pump importujemy FUNKCJĘ, nie blueprint
from routes_pump import pump_heartbeat

app = Flask(__name__)

# istniejące blueprinty
app.register_blueprint(logs_bp)
app.register_blueprint(devices_bp)
app.register_blueprint(telemetry_bp)
app.register_blueprint(light_bp)
app.register_blueprint(watering_bp)
app.register_blueprint(app_api_bp)   # API dla appki

# TU ROBIMY NORMALNY ENDPOINT DLA POMP
@app.route("/pump/heartbeat", methods=["POST"])
def pump_heartbeat_route():
    return pump_heartbeat()


if __name__ == "__main__":
    load_registered_devices()
    print("URL MAP:", app.url_map)
    app.run(host="0.0.0.0", port=8000, debug=True)
