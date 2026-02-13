import matplotlib.pyplot as plt
import numpy as np

# Funkcja przynależności trójkątnej
def triangle_membership(x, a, b, c):
    if a == b and b == c:
        return 1.0 if x == a else 0.0
    
    if a == b and x <= b:
        return 1.0
    
    if b == c and x >= b:
        return 1.0
    
    if x < a or x > c:
        return 0.0
    
    if x <= b:
        return (x - a) / (b - a)
    else:
        return (c - x) / (c - b)

# Funkcja przynależności trapezoidalnej
def trapezoid_membership(x, a, b, c, d):
    if x < a or x > d:
        return 0.0
    
    if x >= b and x <= c:
        return 1.0
    
    if x < b:
        if b == a:
            return 1.0
        return (x - a) / (b - a)
    
    if x > c:
        if d == c:
            return 1.0
        return (d - x) / (d - c)
    
    return 0.0

# Definicje z IrrigationRules.h
# Wilgotność Gleby (0-100%)
SOIL_DRY  = (0, 0, 40)      # Sucha
SOIL_OK   = (30, 50, 70)    # Optymalna
SOIL_WET  = (60, 100, 100)  # Mokra

# Pora dnia (0-24h)
TIME_DAY  = (9, 11, 19, 21) # Dzień



# Temperatura (°C)
TEMP_COLD = (0, 0, 16, 20)    # Zimno (trapez)
TEMP_AVG  = (18, 21, 23)      # Średnia (trójkąt)
TEMP_HOT  = (21, 26, 55, 55)  # Gorąco (trapez)

# Wilgotność powietrza (0-100%)
HUM_LOW    = (0, 0, 40)      # Niska (lewe ramię)
HUM_MEDIUM = (30, 55, 80)    # Średnia
HUM_HIGH   = (70, 100, 100)  # Wysoka (prawe ramię)

# Tworzenie wykresów
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('Funkcje Przynależności - System Nawadniania', fontsize=16, fontweight='bold')

# === WYKRES 1: WILGOTNOŚĆ GLEBY ===
ax1 = axes[0, 0]
soil_range = np.linspace(-10, 110, 500)

soil_dry_vals = [triangle_membership(s, *SOIL_DRY) for s in soil_range]
soil_ok_vals = [triangle_membership(s, *SOIL_OK) for s in soil_range]
soil_wet_vals = [triangle_membership(s, *SOIL_WET) for s in soil_range]

ax1.plot(soil_range, soil_dry_vals, 'brown', linewidth=2.5, label='SOIL_DRY (Sucha)')
ax1.plot(soil_range, soil_ok_vals, 'green', linewidth=2.5, label='SOIL_OK (Optymalna)')
ax1.plot(soil_range, soil_wet_vals, 'blue', linewidth=2.5, label='SOIL_WET (Mokra)')

ax1.fill_between(soil_range, soil_dry_vals, alpha=0.3, color='brown')
ax1.fill_between(soil_range, soil_ok_vals, alpha=0.3, color='green')
ax1.fill_between(soil_range, soil_wet_vals, alpha=0.3, color='blue')

ax1.set_xlabel('Wilgotność gleby [%]', fontsize=11, fontweight='bold')
ax1.set_ylabel('Stopień przynależności μ', fontsize=11, fontweight='bold')
ax1.set_title('Wilgotność Gleby', fontsize=13, fontweight='bold')
ax1.legend(fontsize=10, loc='upper right')
ax1.grid(True, alpha=0.3, linestyle='--')
ax1.set_xlim(-5, 105)
ax1.set_ylim(-0.05, 1.1)
ax1.axhline(y=1.0, color='k', linestyle='--', alpha=0.2)

# === WYKRES 2: TEMPERATURA ===
ax2 = axes[0, 1]
temp_range = np.linspace(-5, 60, 500)

temp_cold_vals = [trapezoid_membership(t, *TEMP_COLD) for t in temp_range]
temp_avg_vals = [triangle_membership(t, *TEMP_AVG) for t in temp_range]
temp_hot_vals = [trapezoid_membership(t, *TEMP_HOT) for t in temp_range]

ax2.plot(temp_range, temp_cold_vals, 'blue', linewidth=2.5, label='TEMP_COLD (Zimno)')
ax2.plot(temp_range, temp_avg_vals, 'orange', linewidth=2.5, label='TEMP_AVG (Średnia)')
ax2.plot(temp_range, temp_hot_vals, 'red', linewidth=2.5, label='TEMP_HOT (Gorąco)')

ax2.fill_between(temp_range, temp_cold_vals, alpha=0.3, color='blue')
ax2.fill_between(temp_range, temp_avg_vals, alpha=0.3, color='orange')
ax2.fill_between(temp_range, temp_hot_vals, alpha=0.3, color='red')

ax2.set_xlabel('Temperatura [°C]', fontsize=11, fontweight='bold')
ax2.set_ylabel('Stopień przynależności μ', fontsize=11, fontweight='bold')
ax2.set_title('Temperatura', fontsize=13, fontweight='bold')
ax2.legend(fontsize=10, loc='upper right')
ax2.grid(True, alpha=0.3, linestyle='--')
ax2.set_xlim(10, 35)
ax2.set_ylim(-0.05, 1.1)
ax2.axhline(y=1.0, color='k', linestyle='--', alpha=0.2)


# === WYKRES 3: PORA DNIA ===
ax3 = axes[1, 0]
time_range = np.linspace(0, 24, 500)


time_day_vals = [trapezoid_membership(t, *TIME_DAY) for t in time_range]

ax3.plot(time_range, time_day_vals, 'darkorange', linewidth=2.5, label='TIME_DAY (Dzień)')

ax3.fill_between(time_range, time_day_vals, alpha=0.3, color='gold')

ax3.set_xlabel('Pora dnia [h]', fontsize=11, fontweight='bold')
ax3.set_ylabel('Stopień przynależności μ', fontsize=11, fontweight='bold')
ax3.set_title('Pora Dnia', fontsize=13, fontweight='bold')
ax3.legend(fontsize=10, loc='upper right')
ax3.grid(True, alpha=0.3, linestyle='--')
ax3.set_xlim(0, 24)
ax3.set_ylim(-0.05, 1.1)
ax3.axhline(y=1.0, color='k', linestyle='--', alpha=0.2)
ax3.set_xticks(range(0, 25, 3))

# === WYKRES 4: WILGOTNOŚĆ POWIETRZA ===
ax4 = axes[1, 1]
hum_range = np.linspace(0, 100, 500)

hum_low_vals = [triangle_membership(h, *HUM_LOW) for h in hum_range]
hum_medium_vals = [triangle_membership(h, *HUM_MEDIUM) for h in hum_range]
hum_high_vals = [triangle_membership(h, *HUM_HIGH) for h in hum_range]

ax4.plot(hum_range, hum_low_vals, 'darkred', linewidth=2.5, label='HUM_LOW (Niska)')
ax4.plot(hum_range, hum_medium_vals, 'orange', linewidth=2.5, label='HUM_MEDIUM (Średnia)')
ax4.plot(hum_range, hum_high_vals, 'blue', linewidth=2.5, label='HUM_HIGH (Wysoka)')

ax4.fill_between(hum_range, hum_low_vals, alpha=0.3, color='darkred')
ax4.fill_between(hum_range, hum_medium_vals, alpha=0.3, color='orange')
ax4.fill_between(hum_range, hum_high_vals, alpha=0.3, color='blue')

ax4.set_xlabel('Wilgotność powietrza [%]', fontsize=11, fontweight='bold')
ax4.set_ylabel('Stopień przynależności μ', fontsize=11, fontweight='bold')
ax4.set_title('Wilgotność Powietrza', fontsize=13, fontweight='bold')
ax4.legend(fontsize=10, loc='upper right')
ax4.grid(True, alpha=0.3, linestyle='--')
ax4.set_xlim(0, 100)
ax4.set_ylim(-0.05, 1.1)
ax4.axhline(y=1.0, color='k', linestyle='--', alpha=0.2)

plt.tight_layout()
plt.savefig('fuzzy_membership_functions.png', dpi=300, bbox_inches='tight')
print("✓ Wykres zapisany jako 'fuzzy_membership_functions.png'")

plt.show()
