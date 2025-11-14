# tsk_logic.py
# Zawiera logikę TSK i funkcję dynamicznej kalibracji.
# Ten plik nie wie nic o Flasku, importuje tylko 'pandas' i 'config'.

import pandas as pd
from datetime import datetime, timedelta

# Importujemy ustawienia z naszego nowego pliku
import config


# --- KLASA TSK ---
class TSKWateringController:
    """
    Kontroler nawadniania oparty na logice rozmytej Takagi-Sugeno.
    """

    def __init__(self, val_in_air: int, val_in_water: int, time_dry: float, time_damp: float, time_wet: float):
        self.dry_val = val_in_air
        self.wet_val = val_in_water
        self.val_range = float(val_in_air - val_in_water)
        self.z_dry = time_dry
        self.z_damp = time_damp
        self.z_wet = time_wet
        if self.val_range <= 0:
            raise ValueError(f"val_in_air ({val_in_air}) musi być większe niż val_in_water ({val_in_water}).")

    def _normalize(self, raw_value: int) -> float:
        percent = (self.dry_val - raw_value) * 100.0 / self.val_range
        percent = max(0.0, min(100.0, percent))
        return percent

    def _membership_dry(self, percent: float) -> float:
        if percent < 40: return max(0.0, (40.0 - percent) / 40.0)
        return 0.0

    def _membership_damp(self, percent: float) -> float:
        if 20 < percent < 80:
            if percent < 50:
                return (percent - 20.0) / 30.0
            else:
                return (80.0 - percent) / 30.0
        return 0.0

    def _membership_wet(self, percent: float) -> float:
        if percent > 60: return min(1.0, (percent - 60.0) / 40.0)
        return 0.0

    def get_watering_time(self, raw_sensor_value: int) -> float:
        moisture_percent = self._normalize(raw_sensor_value)
        w_dry = self._membership_dry(moisture_percent)
        w_damp = self._membership_damp(moisture_percent)
        w_wet = self._membership_wet(moisture_percent)
        numerator = (w_dry * self.z_dry) + (w_damp * self.z_damp) + (w_wet * self.z_wet)
        denominator = w_dry + w_damp + w_wet
        if denominator == 0: return 0.0
        return numerator / denominator


# --- FUNKCJA KALIBRACJI ---
def kalibruj_kontroler_z_danych(csv_file: str, dni_wstecz: int, domyslny_sucho: int, domyslny_mokro: int) -> (int, int):
    """
    Analizuje dane historyczne i zwraca dynamicznie obliczone progi kalibracyjne.
    """
    print(f"--- Rozpoczynam dynamiczną kalibrację z pliku: {csv_file} ---")
    try:
        df = pd.read_csv(csv_file, parse_dates=['timestamp'])
        if 'raw' not in df.columns:
            print(f"Błąd: Brak kolumny 'raw' w pliku {csv_file}.")
            return domyslny_sucho, domyslny_mokro

        data_odciecia = datetime.now() - timedelta(days=dni_wstecz)
        df_recent = df[df['timestamp'] > data_odciecia]

        if len(df_recent) < 20:
            print(
                f"Za mało danych z ostatnich {dni_wstecz} dni ({len(df_recent)} próbek). Używam domyślnej kalibracji.")
            return domyslny_sucho, domyslny_mokro

        print(f"Analizuję {len(df_recent)} próbek z ostatnich {dni_wstecz} dni...")

        # Używamy stałych z pliku config
        q_wet = df_recent['raw'].quantile(config.KWANTYL_MOKRO)
        q_dry = df_recent['raw'].quantile(config.KWANTYL_SUCHO)

        nowy_prog_mokro = int(min(q_wet, domyslny_mokro))
        nowy_prog_sucho = int(max(q_dry, domyslny_sucho))

        if nowy_prog_sucho <= nowy_prog_mokro + 1000:
            print(f"BŁĄD: Progi z danych są sprzeczne. Używam domyślnej kalibracji.")
            return domyslny_sucho, domyslny_mokro

        print("Dynamiczna kalibracja zakończona pomyślnie.")
        return nowy_prog_sucho, nowy_prog_mokro

    except FileNotFoundError:
        print(f"OSTRZEŻENIE: Nie znaleziono pliku danych '{csv_file}'. Używam domyślnej kalibracji.")
        return domyslny_sucho, domyslny_mokro
    except Exception as e:
        print(f"Wystąpił nieoczekiwany błąd podczas kalibracji: {e}. Używam domyślnej kalibracji.")
        return domyslny_sucho, domyslny_mokro