#include <Arduino.h>
#include <ThreeWire.h>
#include <RtcDS1302.h>
#include <DHT.h>
#include "TSKEngine.h"
#include "IrrigationRules.h"

// --- KONFIGURACJA PINÓW DS1302 ---
#define DS1302_CLK 14
#define DS1302_DAT 26
#define DS1302_RST 33

ThreeWire myWire(DS1302_DAT, DS1302_CLK, DS1302_RST); // IO, SCLK, CE
RtcDS1302<ThreeWire> Rtc(myWire);

// --- PINY PERYFERIÓW I WARTOŚCI KALIBRACYJNE ---
#define PIN_SOIL 32
#define PIN_DHT 25
#define PIN_PUMP 27
#define AIR_VALUE 1900   // Wartość czujnika w powietrzu (sucho)
#define WATER_VALUE 1500 // Wartość czujnika w wodzie (mokro)

#define DHTTYPE DHT11
DHT dht(PIN_DHT, DHTTYPE);

// Obiekty kontrolera rozmytego
TSKController fuzzyController;
SystemInputs currentInputs;

// Pomocnicze makro do obliczania rozmiaru tablicy (wymagane przez snprintf_P)
#define countof(a) (sizeof(a) / sizeof(a[0]))

// Funkcja konwertująca czas z RTC na format dziesiętny (np. 14:30 -> 14.5)
float getRealTimeAsFloat()
{
    RtcDateTime now = Rtc.GetDateTime();

    // Weryfikacja poprawności danych z RTC
    if (!Rtc.IsDateTimeValid())
    {
        Serial.println("Błąd: Nieprawidłowe dane z RTC (brak zasilania/baterii).");
        return 12.0; // Wartość bezpieczna (południe)
    }

    return now.Hour() + (now.Minute() / 60.0);
}

void setup()
{
    Serial.begin(115200);

    // Konfiguracja pompy (domyślnie wyłączona)
    pinMode(PIN_PUMP, OUTPUT);
    digitalWrite(PIN_PUMP, LOW);

    dht.begin();

    Serial.println("Inicjalizacja sterownika nawadniania...");

    // --- 1. Konfiguracja i synchronizacja RTC ---
    Rtc.Begin();

    RtcDateTime compiled = RtcDateTime(__DATE__, __TIME__);
    // Ręczne ustawienie daty (opcjonalne nadpisanie)
    RtcDateTime manualTime = RtcDateTime(2026, 1, 19, 21, 30, 0);

    Rtc.SetDateTime(manualTime);

    // Sprawdzenie flagi utraty zasilania
    if (!Rtc.IsDateTimeValid())
    {
        Serial.println("RTC: Wykryto utratę zasilania. Reset do czasu kompilacji.");
        Rtc.SetDateTime(compiled);
    }

    // Wyłączenie ochrony zapisu
    if (Rtc.GetIsWriteProtected())
    {
        Rtc.SetIsWriteProtected(false);
    }

    // Uruchomienie zegara jeśli był zatrzymany
    if (!Rtc.GetIsRunning())
    {
        Rtc.SetIsRunning(true);
    }

    // Weryfikacja czy czas RTC nie jest starszy niż czas kompilacji
    RtcDateTime now = Rtc.GetDateTime();
    if (now < compiled)
    {
        Serial.println("RTC: Czas systemowy nieaktualny. Aktualizacja do czasu kompilacji.");
        Rtc.SetDateTime(compiled);
    }

    // Logowanie aktualnego czasu
    char datestring[20];
    snprintf_P(datestring,
               countof(datestring),
               PSTR("%02u/%02u/%04u %02u:%02u:%02u"),
               now.Month(),
               now.Day(),
               now.Year(),
               now.Hour(),
               now.Minute(),
               now.Second());
    Serial.print("Czas RTC: ");
    Serial.println(datestring);

    // --- 2. Inicjalizacja reguł logiki rozmytej ---
    setupIrrigationRules(fuzzyController);
    Serial.println("Reguły sterowania załadowane.");
}

void readSensors()
{
    // 1. Odczyt wilgotności gleby
    int rawSoil = analogRead(PIN_SOIL);

    // Ograniczenie wartości do zakresu kalibracji
    if (rawSoil > AIR_VALUE)
        rawSoil = AIR_VALUE;
    if (rawSoil < WATER_VALUE)
        rawSoil = WATER_VALUE;

    // Mapowanie wartości analogowej na procenty (0-100%)
    // Dla czujników pojemnościowych niższa wartość napięcia oznacza wyższą wilgotność
    currentInputs.soil_moisture = map(rawSoil, AIR_VALUE, WATER_VALUE, 0, 100);

    // 2. Pobranie czasu
    currentInputs.time_of_day = getRealTimeAsFloat();

    // 3. Odczyt DHT (Temperatura i Wilgotność powietrza)
    float h = dht.readHumidity();
    float t = dht.readTemperature();

    if (isnan(h) || isnan(t))
    {
        Serial.println("Błąd odczytu czujnika DHT.");
        currentInputs.temperature = 20.0; // Wartości domyślne w przypadku awarii
        currentInputs.humidity = 50.0;
    }
    else
    {
        currentInputs.temperature = t;
        currentInputs.humidity = h;
    }

    Serial.printf("Pomiary -> Gleba: %.1f%%, Godzina: %.2f, Temp: %.1fC, Wilg: %.1f%%\n",
                  currentInputs.soil_moisture,
                  currentInputs.time_of_day,
                  currentInputs.temperature,
                  currentInputs.humidity);
}

void activatePump(float durationSeconds)
{
    // Minimalny czas uruchomienia pompy to 0.1s
    if (durationSeconds > 0.1)
    {
        Serial.printf(">> POMPA ON: %.2f s\n", durationSeconds);
        digitalWrite(PIN_PUMP, HIGH);
        delay(durationSeconds * 1000);
        digitalWrite(PIN_PUMP, LOW);
    }
    else
    {
        Serial.println(">> POMPA OFF (brak potrzeby nawadniania)");
    }
}

void loop()
{
    readSensors();

    // Obliczenie czasu nawadniania przez sterownik rozmyty
    float irrigationTime = fuzzyController.compute(currentInputs);

    activatePump(irrigationTime);

    Serial.println("--- Oczekiwanie na kolejny cykl ---");
    delay(5000);
}