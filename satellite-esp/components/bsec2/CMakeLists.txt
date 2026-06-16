idf_component_register(
    INCLUDE_DIRS "include"
    REQUIRES bme68x
)

target_link_libraries(${COMPONENT_LIB} INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/lib/esp32s3/libalgobsec.a
)
