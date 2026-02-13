#ifndef IRRIGATION_RULES_H
#define IRRIGATION_RULES_H

#include "TSKEngine.h"

// --- DEFINICJE ZBIORÓW  ---

// Wilgotność Gleby (0-100%)
const FuzzyTriangle SOIL_DRY  = {0, 0, 40};      // Sucha: plateau do 0%, spadek do 40%
const FuzzyTriangle SOIL_OK   = {30, 50, 70};    // Optymalna: 30-70%, szczyt w 50%
const FuzzyTriangle SOIL_WET  = {60, 100, 100};  // Mokra: wzrost od 60%, plateau od 100%

// Pora dnia (0-24h)
const FuzzyTrapezoid TIME_DAY = {6, 11, 19, 21}; // dzień : wzrost od 9:00, plateau od 11:00 do 19:00 spadek od 21


// Temperatura (°C)
const FuzzyTrapezoid TEMP_COLD = {0, 0, 16, 20};   // Zimno: plateau do 16°C, spadek do 20°C
const FuzzyTriangle  TEMP_AVG  = {18, 21, 23};     // Średnia: 18-23°C, szczyt w 21°C
const FuzzyTrapezoid TEMP_HOT  = {21, 26, 55, 55}; // Gorąco: wzrost od 21°C, plateau od 26°C

// Wilgotność powietrza (0-100%)
const FuzzyTriangle HUM_LOW    = {0, 0, 40};      // Niska: plateau do 0%, spadek do 40%
const FuzzyTriangle HUM_MEDIUM = {30, 55, 80};    // Średnia: 30-80%, szczyt w 55%
const FuzzyTriangle HUM_HIGH   = {70, 100, 100};  // Wysoka: wzrost od 70%, plateau od 100%

// --- HELPERY ---

float is_daytime(const SystemInputs& in) {
    return TIME_DAY.getMembership(in.time_of_day);
}

// --- KONFIGURACJA KONTROLERA ---
void setupIrrigationRules(TSKController& ctrl) {
    
    // R1: Gleba MOKRA -> STOP
    TSKRule r1([](const SystemInputs&){ return 0.0f; });
    r1.addCondition([](const SystemInputs& in){ return SOIL_WET.getMembership(in.soil_moisture); });
    ctrl.addRule(r1);

    // R2: Gleba SUCHA + UPAŁ + DZIEŃ -> MAX (Złożone równanie)
    TSKRule r2([](const SystemInputs& in) {
        // Przykład: baza 5s + korekta temp + korekta wilgotności
        return 5.0f + (in.temperature - 20.0f) * 0.2f + (50.0f - in.humidity) * 0.05f;
    });
    r2.addCondition([](const SystemInputs& in){ return SOIL_DRY.getMembership(in.soil_moisture); });
    r2.addCondition([](const SystemInputs& in){ return TEMP_HOT.getMembership(in.temperature); });
    r2.addCondition(is_daytime);
    ctrl.addRule(r2);

    // R3: Gleba SUCHA + OK TEMP + DZIEŃ -> STANDARD
    TSKRule r3([](const SystemInputs&){ return 4.0f; });
    r3.addCondition([](const SystemInputs& in){ return SOIL_DRY.getMembership(in.soil_moisture); });
    r3.addCondition([](const SystemInputs& in){ return TEMP_AVG.getMembership(in.temperature); });
    r3.addCondition(is_daytime);
    ctrl.addRule(r3);

    // R4: Gleba SUCHA + ZIMNO + DZIEŃ -> MINIMUM
    TSKRule r4([](const SystemInputs&){ return 2.0f; });
    r4.addCondition([](const SystemInputs& in){ return SOIL_DRY.getMembership(in.soil_moisture); });
    r4.addCondition([](const SystemInputs& in){ return TEMP_COLD.getMembership(in.temperature); });
    r4.addCondition(is_daytime);
    ctrl.addRule(r4);
    
    // R5: Gleba OK + SUCHE POWIETRZE -> ZRASZANIE
    TSKRule r5([](const SystemInputs&){ return 1.5f; });
    r5.addCondition([](const SystemInputs& in){ return SOIL_OK.getMembership(in.soil_moisture); });
    r5.addCondition([](const SystemInputs& in){ return HUM_LOW.getMembership(in.humidity); });
    r5.addCondition(is_daytime);
    ctrl.addRule(r5);
    
    // R6: Gleba OK + WYSOKA WILGOTNOŚĆ -> STOP (minimalne parowanie)
    TSKRule r6([](const SystemInputs&){ return 0.0f; });
    r6.addCondition([](const SystemInputs& in){ return SOIL_OK.getMembership(in.soil_moisture); });
    r6.addCondition([](const SystemInputs& in){ return HUM_HIGH.getMembership(in.humidity); });
    r6.addCondition(is_daytime);
    ctrl.addRule(r6);
}

#endif