# config.py
# Centralne miejsce do zarządzania wszystkimi stałymi i ustawieniami.

# --- Konfiguracja Serwera ---
DATA_DIR = "data"

# --- Domyślne progi kalibracyjne (fallback) ---
DEFAULT_CAL_DRY_AIR = 45000  # Wartość "sucho"
DEFAULT_CAL_WET_WATER = 28500  # Wartość "mokro"

# --- Definicja reguł TSK (Parametry wyjściowe) ---
TIME_IF_DRY = 10.0  # Czas lania, gdy 100% sucho
TIME_IF_DAMP = 3.0  # Czas lania, gdy 100% wilgotno
TIME_IF_WET = 0.0  # Czas lania, gdy 100% mokro

# --- Ustawienia kalibracji dynamicznej ---
DNI_DO_ANALIZY = 3  # Ile dni wstecz analizować
KWANTYL_SUCHO = 0.95  # 95-ty percentyl (ignoruje 5% najwyższych, fałszywych pików)
KWANTYL_MOKRO = 0.05  # 5-ty percentyl (ignoruje 5% najniższych, fałszywych dołków)