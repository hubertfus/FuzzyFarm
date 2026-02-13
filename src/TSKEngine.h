#ifndef TSK_ENGINE_H
#define TSK_ENGINE_H

// #include <Arduino.h>
#include <vector>
#include <functional>
#include <algorithm>
#include <cmath>

// --- STRUKTURA WEJŚĆ SYSTEMU ---

struct SystemInputs {
    float soil_moisture; // [%]
    float time_of_day;   // [h] (np. 14.5)
    float temperature;   // [st. C]
    float humidity;      // [%]
};

// --- POMOCNICZE STRUKTURY ROZMYTE ---

struct FuzzyTriangle {
    float a, b, c;

    float getMembership(float x) const {
    if (a == b && b == c) {
        return (x == a) ? 1.0f : 0.0f;
    }


    if (a == b && x <= b) {
        return 1.0f;
    }


    if (b == c && x >= b) {
        return 1.0f;
    }

    if (x < a || x > c) return 0.0f;

    if (x <= b) {
        return (x - a) / (b - a);
    }
    else {
        return (c - x) / (c - b);
    }
}
};

struct FuzzyTrapezoid {
    float a, b, c, d;

    float getMembership(float x) const {
        if (x < a || x > d) return 0.0f;
        
        if (x >= b && x <= c) return 1.0f;
        
        if (x < b) {
            if (b == a) return 1.0f; 
            return (x - a) / (b - a);
        }
        
        if (x > c) {
            if (d == c) return 1.0f;
            return (d - x) / (d - c);
        }
        
        return 0.0f; 
    }
};

// --- KLASY LOGIKI TSK ---

using AntecedentFunc = std::function<float(const SystemInputs&)>;
using ConsequentFunc = std::function<float(const SystemInputs&)>;

class TSKRule {
private:
    std::vector<AntecedentFunc> antecedents;
    ConsequentFunc consequent;

public:
    TSKRule(ConsequentFunc output_func) : consequent(output_func) {}

    void addCondition(AntecedentFunc condition) {
        antecedents.push_back(condition);
    }

    std::pair<float, float> evaluate(const SystemInputs& inputs) const {
        if (antecedents.empty()) return {0.0f, 0.0f};

        float weight = 1.0f;
        for (const auto& func : antecedents) {
            weight *= func(inputs);
            if (weight == 0.0f) break; 
        }


        float output_y = 0.0f;
        if (weight > 0.0f) {
            output_y = consequent(inputs);
        }

        return {weight, output_y};
    }
};

class TSKController {
private:
    std::vector<TSKRule> rules;

public:
    void addRule(const TSKRule& rule) {
        rules.push_back(rule);
    }

    void clearRules() {
        rules.clear();
    }

    float compute(const SystemInputs& inputs) {
        double numerator = 0.0;
        double denominator = 0.0;

        for (const auto& rule : rules) {
            std::pair<float, float> result = rule.evaluate(inputs);
            float weight = result.first;
            float y = result.second;
            
            if (weight > 0.0f) {
                numerator += weight * y;
                denominator += weight;
            }
        }

        if (denominator < 1e-6) {
            return 0.0f;
        }

        float result = static_cast<float>(numerator / denominator);
        
        if (result < 0.0f) return 0.0f;
        if (result > 10.0f) return 10.0f;
        return result;
    }
};

#endif