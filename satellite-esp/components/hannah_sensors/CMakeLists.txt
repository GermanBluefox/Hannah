idf_component_register(
    SRCS "hannah_sensors.c"
    INCLUDE_DIRS "."
    REQUIRES
        driver
        esp_driver_i2c
)
