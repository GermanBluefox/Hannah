idf_component_register(
    SRCS "hannah_ota.c"
    INCLUDE_DIRS "."
    REQUIRES
        hannah_config
        hannah_net
        esp_http_client
        esp_https_ota
        esp_app_format
        espressif__cjson
)
