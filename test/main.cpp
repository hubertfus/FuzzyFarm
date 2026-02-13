#include <iostream>
#include <fstream>
#include <vector>

#include "../src/TSKEngine.h"
#include "../src/IrrigationRules.h" 

int main() {
    // 1. Inicjalizacja kontrolera
    TSKController ctrl;
    setupIrrigationRules(ctrl);

    // 2. Otwarcie pliku do zapisu
    std::ofstream file("wyniki_symulacji.csv");
    if (!file.is_open()) {
        std::cerr << "Blad: Nie mozna otworzyc pliku do zapisu!" << std::endl;
        return 1;
    }

    // Nagłówek CSV
    file << "Soil_Moisture[%],Time[h],Temperature[C],Humidity[%],Output_Water_Amount\n";
    std::cout << "generowanie CSV..." << std::endl;

    // Definicja kroków
    float soil_step = 2.0f;
    float time_step = 0.5f;
    float temp_step = 2.0f;
    float hum_step = 10.0f;
    long counter = 0;

    // Pętle symulacyjne
    for (float time = 0; time <= 24.0f; time += time_step) {
        for (float soil = 0; soil <= 100.0f; soil += soil_step) {
            for (float temp = 0; temp <= 40.0f; temp += temp_step) {
                for (float hum = 0; hum <= 100.0f; hum += hum_step) {

                    SystemInputs inputs;
                    inputs.soil_moisture = soil;
                    inputs.time_of_day = time;
                    inputs.temperature = temp;
                    inputs.humidity = hum;

                    float output = ctrl.compute(inputs);

                    file << inputs.soil_moisture << ","
                         << inputs.time_of_day << ","
                         << inputs.temperature << ","
                         << inputs.humidity << ","
                         << output << "\n";
                    counter++;
                }
            }
        }
    }

    file.close();
    std::cout << "Wygenerowano " << counter << " rekordow." << std::endl;
    return 0;
}