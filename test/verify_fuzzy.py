import numpy as np
import pandas as pd
from pyit2fls import T1TSK, T1FS, tri_mf, trapezoid_mf
import matplotlib.pyplot as plt

# Definicja uniwersów
soil_universe = np.linspace(0.0, 100.0, 1000)
time_universe = np.linspace(0.0, 24.0, 1000)
temp_universe = np.linspace(0.0, 60.0, 1000)
hum_universe  = np.linspace(0.0, 100.0, 1000)

# Epsilon żeby uniknąć a == b lub c == d
e = 1e-5 

# 1. Soil Moisture (0-100%)
soil_dry = T1FS(soil_universe, tri_mf, [0-e, 0, 40, 1.0])
soil_ok  = T1FS(soil_universe, tri_mf, [30, 50, 70, 1.0])
soil_wet = T1FS(soil_universe, tri_mf, [60, 100, 100+e, 1.0])

# 2. Time of Day (0-24h)
time_day = T1FS(time_universe, trapezoid_mf, [6, 11, 19, 21, 1.0])

# 3. Temperature (st. C)
temp_cold = T1FS(temp_universe, trapezoid_mf, [0-e, 0, 16, 20, 1.0])
temp_avg  = T1FS(temp_universe, tri_mf, [18, 21, 23, 1.0])
temp_hot  = T1FS(temp_universe, trapezoid_mf, [21, 26, 55, 55+e, 1.0])

# 4. Humidity (0-100%)
hum_low  = T1FS(hum_universe, tri_mf, [0-e, 0, 40, 1.0])
hum_high = T1FS(hum_universe, tri_mf, [70, 100, 100+e, 1.0])


def out_stop(x1, x2, x3, x4):
    return 0.0

def out_max_complex(soil, time, temp, hum):
    val = 5.0 + (temp - 20.0) * 0.2 + (50.0 - hum) * 0.05

    return val

def out_standard(x1, x2, x3, x4):
    return 4.0

def out_min(x1, x2, x3, x4):
    return 2.0

def out_mist(x1, x2, x3, x4):
    return 1.5

# --- KONFIGURACJA KONTROLERA TSK ---

my_tsk = T1TSK()
my_tsk.add_input_variable('soil')
my_tsk.add_input_variable('time')
my_tsk.add_input_variable('temp')
my_tsk.add_input_variable('hum')
my_tsk.add_output_variable('water')

# --- REGUŁY ---

# R1: Gleba MOKRA -> STOP
my_tsk.add_rule([('soil', soil_wet)], [('water', out_stop)])

# R2: Gleba SUCHA + UPAŁ + DZIEŃ -> MAX (Złożone równanie)
my_tsk.add_rule([('soil', soil_dry), ('temp', temp_hot), ('time', time_day)], 
                [('water', out_max_complex)])

# R3: Gleba SUCHA + OK TEMP + DZIEŃ -> STANDARD
my_tsk.add_rule([('soil', soil_dry), ('temp', temp_avg), ('time', time_day)], 
                [('water', out_standard)])

# R4: Gleba SUCHA + ZIMNO + DZIEŃ -> MINIMUM
my_tsk.add_rule([('soil', soil_dry), ('temp', temp_cold), ('time', time_day)], 
                [('water', out_min)])

# R5: Gleba OK + SUCHE POWIETRZE -> ZRASZANIE
# Warunek: is_daytime jest też w C++
my_tsk.add_rule([('soil', soil_ok), ('hum', hum_low), ('time', time_day)], 
                [('water', out_mist)])

# R6: Gleba OK + WYSOKA WILGOTNOŚĆ -> STOP
my_tsk.add_rule([('soil', soil_ok), ('hum', hum_high), ('time', time_day)], 
                [('water', out_stop)])



csv_path = 'wyniki_symulacji.csv' 
try:
    df = pd.read_csv(csv_path)
except FileNotFoundError:
    print(f"BŁĄD: Nie znaleziono pliku {csv_path}.")
    exit()

print(f"Wczytano {len(df)} rekordów z {csv_path}.")

cpp_outputs = []
py_outputs = []
errors = []

for index, row in df.iterrows():
    # Pobranie danych wejściowych
    s = row['Soil_Moisture[%]']
    t = row['Time[h]']
    tmp = row['Temperature[C]']
    h = row['Humidity[%]']
    
    cpp_val = row['Output_Water_Amount']
    
    res_dict = my_tsk.evaluate({'soil': s, 'time': t, 'temp': tmp, 'hum': h}, (s, t, tmp, h))
    py_val = res_dict['water']
    
    if py_val is None or np.isnan(py_val):
        py_val = 0.0
    
    if py_val < 0.0: py_val = 0.0
    if py_val > 10.0: py_val = 10.0

    cpp_outputs.append(cpp_val)
    py_outputs.append(py_val)
    errors.append(abs(cpp_val - py_val))

max_error = max(errors)
avg_error = sum(errors) / len(errors)

print("\n--- WYNIKI PORÓWNANIA ---")
print(f"Liczba próbek: {len(df)}")
print(f"Maksymalny błąd (różnica): {max_error:.6f}")
print(f"Średni błąd: {avg_error:.6f}")

if max_error < 0.01:
    print("✅ WYNIK: SUKCES! Implementacja C++ i Python są zgodne.")
else:
    print("⚠️ WYNIK: Istnieją różnice.")

plt.figure(figsize=(12, 6))

step = max(1, len(df) // 200) 
indices = range(0, len(df), step)
sample_cpp = [cpp_outputs[i] for i in indices]
sample_py = [py_outputs[i] for i in indices]

plt.plot(indices, sample_cpp, 'b-', label='C++ Output', linewidth=2, alpha=0.7)
plt.plot(indices, sample_py, 'r--', label='Python (pyit2fls)', linewidth=2, alpha=0.7)
plt.title('Porównanie wyjść sterownika')
plt.legend()
plt.grid(True)

plt.show()