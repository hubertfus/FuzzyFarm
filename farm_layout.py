# farm_layout.py
import json
import os

# Bazowy katalog (tam gdzie leży ten plik)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FARM_LAYOUT_FILE = os.path.join(DATA_DIR, "farm_layout.json")

# Fallback jak nie ma pliku – możesz zmienić pod swoje deviceId
DEFAULT_LAYOUT = {
    "rack-1": {
        "plants": {
            "plant-1": {
                "name": "Lewa doniczka",
                "soilDeviceId": "PICO-e6642815",  # BEZ suffixu "-soil"
                "pump": 1
            },
            "plant-2": {
                "name": "Prawa doniczka",
                "soilDeviceId": "PICO-abcdef12",
                "pump": 2
            }
        }
    }
}


def load_layout():
    print(f"[FARM_LAYOUT] Szukam pliku: {FARM_LAYOUT_FILE}")

    if not os.path.exists(FARM_LAYOUT_FILE):
        print(f"[FARM_LAYOUT] Brak pliku, używam DEFAULT_LAYOUT")
        return DEFAULT_LAYOUT

    try:
        with open(FARM_LAYOUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[FARM_LAYOUT] Wczytano layout z pliku.")
        return data
    except Exception as e:
        print(f"[FARM_LAYOUT] Błąd wczytywania {FARM_LAYOUT_FILE}: {e}")
        print("[FARM_LAYOUT] Używam DEFAULT_LAYOUT")
        return DEFAULT_LAYOUT


LAYOUT = load_layout()


def get_plants_for_farm(farm_id: str):
    farm = LAYOUT.get(farm_id, {})
    return farm.get("plants", {})


def get_plant_by_soil_device(farm_id: str, soil_device_id: str):
    """
    Znajdź roślinę na danej farmie po deviceId czujnika gleby.
    Zwraca dict: {"plantId": "...", "name": "...", "pump": int, "soilDeviceId": "..."} lub None.
    """
    plants = get_plants_for_farm(farm_id)
    for plant_id, info in plants.items():
        if info.get("soilDeviceId") == soil_device_id:
            return {
                "plantId": plant_id,
                **info
            }
    return None


def get_pump_for_plant(farm_id: str, plant_id: str):
    """
    Zwraca numer pompki (int) dla danej rośliny, albo None.
    """
    plants = get_plants_for_farm(farm_id)
    info = plants.get(plant_id)
    if not info:
        return None
    return info.get("pump")
