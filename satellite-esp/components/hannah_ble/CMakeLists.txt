idf_component_register(
    SRCS "hannah_ble.c"
    INCLUDE_DIRS "."
    REQUIRES
        hannah_config
        hannah_net
        bt
        espressif__cjson
        esp_timer
)
