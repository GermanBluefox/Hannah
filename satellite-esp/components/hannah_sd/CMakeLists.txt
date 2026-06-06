idf_component_register(
    SRCS "hannah_sd.c"
    INCLUDE_DIRS "."
    REQUIRES
        driver
        esp_driver_spi
        sdmmc
        fatfs
        hannah_config
)
