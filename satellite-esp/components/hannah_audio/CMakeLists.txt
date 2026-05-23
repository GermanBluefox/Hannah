idf_component_register(
    SRCS
        "hannah_audio.c"
        "${CMAKE_CURRENT_SOURCE_DIR}/../../../audiolib/src/hannah_audio.c"
    INCLUDE_DIRS "."
    PRIV_INCLUDE_DIRS
        "${CMAKE_CURRENT_SOURCE_DIR}/../../../audiolib/include"
    REQUIRES
        hannah_config
        driver
        esp_driver_i2s
        esp_driver_gpio
        hannah_net
        hannah_led
        hannah_wakeword
)
