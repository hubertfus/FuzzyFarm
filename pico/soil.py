# ==============================================
#  SOIL SENSOR (SEN0193) for Raspberry Pi Pico W (MicroPython)
#  Odczyt z ADC0 (GP26) – surowy odczyt gleby
#  Provisioning + telemetria do serwera
# ==============================================
import network, socket, time, json, machine

# ========= STAŁE URZĄDZENIA =========
DEVICE_TYPE = "soil-sensor"
DEVICE_NAME = "SoilSensor-1"
FARM_ID     = "rack-1"

# ========= KONFIGURACJA =========
CONFIG_FILE  = "config.json"
AP_PASSWORD  = "12345678"
AP_PORT      = 80
TELEMETRY_EVERY_SEC = 30

# ========= PINY =========
SOIL_ADC_PIN = 26
SOIL_SAMPLES = 8   # ile próbek do uśredniania

# ========= NARZĘDZIA =========
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print("Brak lub zły config.json:", e)
        return None

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

def get_device_id():
    uid = machine.unique_id()
    hexid = "".join("{:02x}".format(b) for b in uid)
    return "PICO-" + hexid[:8]

def connect_sta(ssid, password, timeout=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print("Łączenie z Wi-Fi:", ssid)
    wlan.connect(ssid, password)
    t0 = time.time()
    while not wlan.isconnected() and time.time() - t0 < timeout:
        time.sleep(1)
        print("...")
    if wlan.isconnected():
        print("Połączono! IP:", wlan.ifconfig()[0])
        return wlan
    print("Nie udało się połączyć z Wi-Fi")
    return None

def http_post(url, data_dict):
    try:
        assert url.startswith("http://")
        without = url[7:]
        if "/" in without:
            host_port, path = without.split("/", 1); path = "/" + path
        else:
            host_port, path = without, "/"
        if ":" in host_port:
            host, port = host_port.split(":"); port = int(port)
        else:
            host, port = host_port, 80
        addr = socket.getaddrinfo(host, port)[0][-1]
        s = socket.socket()
        s.connect(addr)
        body = json.dumps(data_dict)
        req = (
            "POST {path} HTTP/1.1\r\n"
            "Host: {host}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {length}\r\n"
            "Connection: close\r\n"
            "\r\n"
            "{body}"
        ).format(path=path, host=host, length=len(body), body=body)
        s.send(req.encode())
        resp = s.recv(512)
        print("HTTP POST resp:", resp)
        s.close()
        return True
    except Exception as e:
        print("POST error:", e)
        return False

def send_response(cl, code, content_type, body):
    resp = "HTTP/1.1 {} OK\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}".format(
        code, content_type, len(body), body
    )
    cl.send(resp)

# ========= PROVISIONING (CONFIG) =========
def start_ap_and_wait_for_config():
    device_id = get_device_id()
    ap_ssid = device_id
    ap = network.WLAN(network.AP_IF)
    if AP_PASSWORD:
        ap.config(essid=ap_ssid, password=AP_PASSWORD)
    else:
        ap.config(essid=ap_ssid)
    ap.active(True)
    print("AP uruchomiony, SSID:", ap_ssid)
    print("IP:", ap.ifconfig()[0])
    print("Czekam na POST /config ...")

    addr = socket.getaddrinfo("0.0.0.0", AP_PORT)[0][-1]
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr); s.listen(1)

    while True:
        cl = None
        try:
            cl, remote = s.accept()
            print("Połączenie od", remote)
            req = cl.recv(2048).decode()
            parts = req.split("\r\n\r\n", 1)
            headers = parts[0]
            body = parts[1] if len(parts) > 1 else ""
            first_line = headers.split("\r\n", 1)[0]
            clen = 0
            for line in headers.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    clen = int(line.split(":",1)[1].strip())
            while len(body) < clen:
                more = cl.recv(1024).decode()
                if not more: break
                body += more

            if first_line.startswith("POST /config"):
                print("Body:", body)
                try:
                    data = json.loads(body)
                except Exception:
                    send_response(cl, 400, "application/json", json.dumps({"status":"error","reason":"bad json"}))
                    cl.close(); continue

                needed = ["targetSsid","targetPassword","server"]
                missing = [k for k in needed if k not in data]
                if missing:
                    send_response(cl, 400, "application/json", json.dumps({"status":"error","reason":"missing "+",".join(missing)}))
                    cl.close(); continue

                save_config(data)
                send_response(cl, 200, "application/json", json.dumps({"status":"ok","message":"config saved"}))
                cl.close()
                print("Konfiguracja zapisana, restart za 2s...")
                time.sleep(2)
                machine.reset(); return

            elif first_line.startswith("GET /status"):
                payload = {"status":"ap-mode","deviceId":device_id,"deviceType":DEVICE_TYPE,"deviceName":DEVICE_NAME,"farmId":FARM_ID}
                send_response(cl, 200, "application/json", json.dumps(payload)); cl.close()
            else:
                html = "<html><body><h1>Pico SOIL config</h1><p>Wyślij POST /config z JSON (targetSsid, targetPassword, server).</p></body></html>"
                send_response(cl, 200, "text/html", html); cl.close()
        except Exception as e:
            print("Błąd obsługi żądania:", e)
            try: cl and cl.close()
            except: pass

# ========= SEN0193 =========
_soil_adc = machine.ADC(machine.Pin(SOIL_ADC_PIN))

def read_soil_raw(samples=SOIL_SAMPLES, delay_ms=2):
    try:
        total = 0
        for _ in range(samples):
            total += _soil_adc.read_u16()
            time.sleep_ms(delay_ms)
        val = total // samples
        return val
    except Exception as e:
        print("SEN0193 read err:", e)
        return None

# ========= MAIN =========
def main():
    cfg = load_config()
    if cfg is None:
        start_ap_and_wait_for_config()
        return

    ssid = cfg.get("targetSsid"); password = cfg.get("targetPassword",""); server = cfg.get("server")
    device_id = get_device_id()

    wlan = connect_sta(ssid, password)
    if not wlan:
        print("Wracam do trybu AP"); start_ap_and_wait_for_config(); return

    # provision
    if server:
        prov_url = server.rstrip("/") + "/provision"
        payload = {
            "deviceId": device_id,
            "deviceType": DEVICE_TYPE,
            "deviceName": DEVICE_NAME,
            "farmId": FARM_ID,
            "ip": wlan.ifconfig()[0],
        }
        print("Wysyłam provision do", prov_url)
        http_post(prov_url, payload)

    tele_url = server.rstrip("/") + "/telemetry" if server else None
    print("Start telemetry loop, co", TELEMETRY_EVERY_SEC, "s")

    while True:
        soil_raw = read_soil_raw()
        telemetry = {
            "deviceId": device_id,
            "deviceType": DEVICE_TYPE,
            "farmId": FARM_ID,
            "ts": time.time(),
            "soil": {
                "raw": soil_raw
            }
        }
        print("Telemetry:", telemetry)
        if tele_url:
            ok = http_post(tele_url, telemetry)
            if not ok:
                print("Telemetry send failed")
        time.sleep(TELEMETRY_EVERY_SEC)

if __name__ == "__main__":
    main()

