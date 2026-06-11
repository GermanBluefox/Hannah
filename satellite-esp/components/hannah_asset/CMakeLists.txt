idf_component_register(
    SRCS "hannah_asset.c"
    INCLUDE_DIRS "."
    REQUIRES
        hannah_audio
        hannah_config
        nvs_flash
        spiffs
        esp_http_client
        espressif__cjson
)
