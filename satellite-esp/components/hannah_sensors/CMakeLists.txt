idf_component_register(
    SRCS "hannah_sensors.c"
    INCLUDE_DIRS "."
    REQUIRES
        driver
        esp_driver_i2c
        hannah_net
        hannah_config
        nvs_flash
        esp_timer
    EMBED_FILES "bme680_iaq_33v_3s_4d.bin"
)

# IDF 6.0 component_requirements.py hat einen Windows-Pfad-Bug der REQUIRES-
# Propagation für hannah_sensors bricht. bme68x/bsec2 daher direkt per CMake.
target_include_directories(${COMPONENT_LIB} PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/../bme68x
    ${CMAKE_CURRENT_LIST_DIR}/../bsec2/include
)

target_link_libraries(${COMPONENT_LIB} PRIVATE idf::bme68x idf::bsec2)
