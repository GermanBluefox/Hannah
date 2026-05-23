#pragma once

#include <stdbool.h>

typedef struct {
    float temperature;    /* °C */
    float pressure;       /* hPa */
    float humidity;       /* % rel. */
    float gas_resistance; /* Ω — VOC-Gassensor-Rohwiderstand; NAN = ungültig */
} hannah_sensor_data_t;

void hannah_sensors_init(void);

/* Letzte gelesene Werte — thread-safe. Gibt false zurück wenn noch keine Daten. */
bool hannah_sensors_get(hannah_sensor_data_t *out);
