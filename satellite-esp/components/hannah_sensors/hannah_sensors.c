#include "hannah_sensors.h"
#include "hannah_net.h"
#include "hannah_config.h"

#include <math.h>
#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c_master.h"

static const char *TAG = "sensors";

#define I2C_TIMEOUT_MS  50

static i2c_master_bus_handle_t s_bus      = NULL;
static bool                    s_ready    = false;
static hannah_sensor_data_t    s_last     = {0};
static volatile bool           s_has_data = false;

/* ========================================================================
 * BME680
 * ======================================================================== */
#if CONFIG_HANNAH_SENSOR_TYPE_BME680

#define BME680_ADDR              CONFIG_HANNAH_SENSOR_BME680_ADDR
#define BME680_REG_CHIP_ID       0xD0
#define BME680_REG_RESET         0xE0
#define BME680_REG_CTRL_HUM      0x72
#define BME680_REG_CTRL_GAS1     0x71
#define BME680_REG_CTRL_MEAS     0x74
#define BME680_REG_CONFIG        0x75
#define BME680_REG_GAS_WAIT0     0x64
#define BME680_REG_RES_HEAT0     0x5A
#define BME680_REG_MEAS_STATUS   0x1D
#define BME680_REG_DATA0         0x1F
#define BME680_REG_GAS_R_MSB     0x2A
#define BME680_CALIB1_ADDR       0x8A
#define BME680_CALIB1_LEN        23
#define BME680_CALIB2_ADDR       0xE1
#define BME680_CALIB2_LEN        16
#define BME680_REG_RES_HEAT_VAL   0x00
#define BME680_REG_RES_HEAT_RANGE 0x02
#define BME680_REG_RANGE_SW_ERR   0x04
#define BME680_CHIP_ID           0x61
#define BME680_RESET_CMD         0xB6
#define BME680_NEW_DATA_MSK      0x80
#define HEATER_TARGET_TEMP       320
#define HEATER_DURATION_MS       150

static const uint32_t s_gas_lut1[16] = {
    2147483647UL, 2147483647UL, 2147483647UL, 2147483647UL,
    2147483647UL, 2126008810UL, 2147483647UL, 2130303777UL,
    2147483647UL, 2147483647UL, 2143188679UL, 2136746228UL,
    2147483647UL, 2126008810UL, 2147483647UL, 2147483647UL
};
static const uint32_t s_gas_lut2[16] = {
    4096000000UL, 2048000000UL, 1024000000UL,  512000000UL,
     255744255UL,  127110228UL,   64000000UL,   32258064UL,
      16016016UL,    8000000UL,    4000000UL,    2000000UL,
       1000000UL,     500000UL,     250000UL,     125000UL
};

typedef struct {
    uint16_t par_t1; int16_t par_t2; int8_t par_t3;
    uint16_t par_p1; int16_t par_p2; int8_t par_p3;
    int16_t par_p4; int16_t par_p5; int8_t par_p6; int8_t par_p7;
    int16_t par_p8; int16_t par_p9; uint8_t par_p10;
    uint16_t par_h1; uint16_t par_h2;
    int8_t par_h3; int8_t par_h4; int8_t par_h5; uint8_t par_h6; int8_t par_h7;
    int8_t par_g1; int16_t par_g2; int8_t par_g3;
    uint8_t res_heat_range; int8_t res_heat_val; int8_t range_sw_err;
    int32_t t_fine;
} bme680_calib_t;

static i2c_master_dev_handle_t s_dev   = NULL;
static bme680_calib_t          s_calib = {0};

static esp_err_t bme_read(uint8_t reg, uint8_t *buf, size_t len) {
    return i2c_master_transmit_receive(s_dev, &reg, 1, buf, len, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
}
static esp_err_t bme_write(uint8_t reg, uint8_t val) {
    uint8_t b[2] = {reg, val};
    return i2c_master_transmit(s_dev, b, 2, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
}

static bool bme680_read_calib(void) {
    uint8_t c1[BME680_CALIB1_LEN], c2[BME680_CALIB2_LEN], tmp;
    if (bme_read(BME680_CALIB1_ADDR, c1, BME680_CALIB1_LEN) != ESP_OK) return false;
    if (bme_read(BME680_CALIB2_ADDR, c2, BME680_CALIB2_LEN) != ESP_OK) return false;
    s_calib.par_t2  = (int16_t)((uint16_t)c1[1] << 8 | c1[0]);
    s_calib.par_t3  = (int8_t)c1[2];
    s_calib.par_p1  = (uint16_t)c1[5] << 8 | c1[4];
    s_calib.par_p2  = (int16_t)((uint16_t)c1[7]  << 8 | c1[6]);
    s_calib.par_p3  = (int8_t)c1[8];
    s_calib.par_p4  = (int16_t)((uint16_t)c1[11] << 8 | c1[10]);
    s_calib.par_p5  = (int16_t)((uint16_t)c1[13] << 8 | c1[12]);
    s_calib.par_p7  = (int8_t)c1[14]; s_calib.par_p6 = (int8_t)c1[15];
    s_calib.par_p8  = (int16_t)((uint16_t)c1[19] << 8 | c1[18]);
    s_calib.par_p9  = (int16_t)((uint16_t)c1[21] << 8 | c1[20]);
    s_calib.par_p10 = c1[22];
    s_calib.par_h2  = (uint16_t)((uint16_t)c2[0] << 4 | c2[1] >> 4);
    s_calib.par_h1  = (uint16_t)((uint16_t)c2[2] << 4 | (c2[1] & 0x0F));
    s_calib.par_h3  = (int8_t)c2[3]; s_calib.par_h4 = (int8_t)c2[4];
    s_calib.par_h5  = (int8_t)c2[5]; s_calib.par_h6 = c2[6]; s_calib.par_h7 = (int8_t)c2[7];
    s_calib.par_t1  = (uint16_t)c2[9] << 8 | c2[8];
    s_calib.par_g2  = (int16_t)((uint16_t)c2[11] << 8 | c2[10]);
    s_calib.par_g1  = (int8_t)c2[12]; s_calib.par_g3 = (int8_t)c2[13];
    bme_read(BME680_REG_RES_HEAT_VAL,   &tmp, 1); s_calib.res_heat_val   = (int8_t)tmp;
    bme_read(BME680_REG_RES_HEAT_RANGE, &tmp, 1); s_calib.res_heat_range = (tmp >> 4) & 0x03;
    bme_read(BME680_REG_RANGE_SW_ERR,   &tmp, 1); s_calib.range_sw_err   = ((int8_t)tmp & (int8_t)0xF0) >> 4;
    return true;
}

static float comp_temp(uint32_t adc_t) {
    double v1 = ((double)adc_t/16384.0 - (double)s_calib.par_t1/1024.0) * (double)s_calib.par_t2;
    double v2 = (((double)adc_t/131072.0 - (double)s_calib.par_t1/8192.0) *
                 ((double)adc_t/131072.0 - (double)s_calib.par_t1/8192.0)) * (double)s_calib.par_t3 * 16.0;
    s_calib.t_fine = (int32_t)(v1 + v2);
    return (float)((v1 + v2) / 5120.0);
}
static float comp_press(uint32_t adc_p) {
    double v1 = (double)s_calib.t_fine/2.0 - 64000.0;
    double v2 = v1*v1*(double)s_calib.par_p6/131072.0 + v1*(double)s_calib.par_p5*2.0;
    v2 = v2/4.0 + (double)s_calib.par_p4*65536.0;
    v1 = ((double)s_calib.par_p3*v1*v1/16384.0 + (double)s_calib.par_p2*v1)/524288.0;
    v1 = (1.0 + v1/32768.0)*(double)s_calib.par_p1;
    if (v1 == 0.0) return 0.0f;
    double p = 1048576.0 - (double)adc_p;
    p = ((p - v2/4096.0)*6250.0)/v1;
    v1 = (double)s_calib.par_p9*p*p/2147483648.0;
    v2 = p*((double)s_calib.par_p8/32768.0);
    double v3 = (p/256.0)*(p/256.0)*(p/256.0)*((double)s_calib.par_p10/131072.0);
    p += (v1 + v2 + v3 + (double)s_calib.par_p7*128.0)/16.0;
    return (float)(p/100.0);
}
static float comp_hum(uint16_t adc_h, float tc) {
    double v1 = (double)adc_h - ((double)s_calib.par_h1*16.0) - (tc*(double)s_calib.par_h3/100.0*0.5);
    double v2 = (double)s_calib.par_h2/262144.0*(1.0 + tc*(double)s_calib.par_h4/100.0 + tc*tc*(double)s_calib.par_h5/10000000.0*0.01);
    double h  = v1*v2*(1.0 + (double)s_calib.par_h6/16384.0*v1 + (double)s_calib.par_h7/2097152.0*v1*v1);
    if (h > 100.0) h = 100.0;
    if (h < 0.0)   h = 0.0;
    return (float)h;
}
static float comp_gas(uint16_t adc_gas, uint8_t gas_range) {
    int64_t v1 = (int64_t)((1340 + (5*(int64_t)s_calib.range_sw_err))*(int64_t)s_gas_lut1[gas_range]) >> 16;
    uint64_t v2 = (uint64_t)(((int64_t)adc_gas << 15) - (int64_t)16777216 + v1);
    int64_t v3 = (int64_t)s_gas_lut2[gas_range] * v1 >> 9;
    return (float)((v3 + (int64_t)(v2 >> 1)) / (int64_t)v2);
}
static uint8_t calc_res_heat(int32_t amb, int32_t target) {
    if (target < 200) target = 200;
    if (target > 400) target = 400;
    int32_t v1 = ((amb*(int32_t)s_calib.par_g3)/1000)*256;
    int32_t v2 = ((int32_t)s_calib.par_g1+784)*((((((int32_t)s_calib.par_g2+154009)*target*5)/100)+3276800)/10);
    int32_t v3 = v1 + (v2/2);
    int32_t v4 = v3/((int32_t)s_calib.res_heat_range+4);
    int32_t v5 = (131*(int32_t)s_calib.res_heat_val)+65536;
    return (uint8_t)(((v4/v5)-250)*34+50)/100;
}
static uint8_t calc_gas_wait(uint16_t dur) {
    uint8_t f = 0; while (dur > 0x3F) { dur /= 4; f++; } return (uint8_t)(dur + (f*64));
}

static bool sensor_init(void) {
    uint8_t id = 0;
    if (bme_read(BME680_REG_CHIP_ID, &id, 1) != ESP_OK || id != BME680_CHIP_ID) {
        ESP_LOGE(TAG, "BME680 nicht gefunden (ID=0x%02x)", id); return false;
    }
    bme_write(BME680_REG_RESET, BME680_RESET_CMD);
    vTaskDelay(pdMS_TO_TICKS(10));
    if (!bme680_read_calib()) return false;
    bme_write(BME680_REG_CTRL_HUM,  0x01);
    bme_write(BME680_REG_CONFIG,    0x00);
    bme_write(BME680_REG_CTRL_GAS1, 0x10);
    bme_write(BME680_REG_RES_HEAT0, calc_res_heat(25, HEATER_TARGET_TEMP));
    bme_write(BME680_REG_GAS_WAIT0, calc_gas_wait(HEATER_DURATION_MS));
    ESP_LOGI(TAG, "BME680 gefunden");
    return true;
}

static bool sensor_measure(hannah_sensor_data_t *out) {
    int32_t amb = s_has_data ? (int32_t)s_last.temperature : 25;
    bme_write(BME680_REG_RES_HEAT0, calc_res_heat(amb, HEATER_TARGET_TEMP));
    bme_write(BME680_REG_CTRL_MEAS, (0x02 << 5) | (0x03 << 2) | 0x01);
    uint8_t status = 0;
    for (int i = 0; i < 30; i++) {
        vTaskDelay(pdMS_TO_TICKS(10));
        bme_read(BME680_REG_MEAS_STATUS, &status, 1);
        if (status & BME680_NEW_DATA_MSK) break;
    }
    if (!(status & BME680_NEW_DATA_MSK)) { ESP_LOGW(TAG, "BME680 Timeout"); return false; }
    uint8_t data[8];
    if (bme_read(BME680_REG_DATA0, data, 8) != ESP_OK) return false;
    uint32_t adc_p = ((uint32_t)data[0] << 12) | ((uint32_t)data[1] << 4) | (data[2] >> 4);
    uint32_t adc_t = ((uint32_t)data[3] << 12) | ((uint32_t)data[4] << 4) | (data[5] >> 4);
    uint16_t adc_h = ((uint16_t)data[6] << 8) | data[7];
    uint8_t gas[2]; bme_read(BME680_REG_GAS_R_MSB, gas, 2);
    uint16_t adc_gas  = ((uint16_t)gas[0] << 2) | (gas[1] >> 6);
    uint8_t  gas_range = gas[1] & 0x0F;
    bool     gas_valid = (gas[1] >> 5) & 0x01;
    out->temperature   = comp_temp(adc_t);
    out->pressure      = comp_press(adc_p);
    out->humidity      = comp_hum(adc_h, out->temperature);
    out->gas_resistance = gas_valid ? comp_gas(adc_gas, gas_range) : NAN;
    return true;
}

/* ========================================================================
 * BMP280 + AHT20
 * ======================================================================== */
#else

#define BMP280_ADDR      CONFIG_HANNAH_SENSOR_BMP280_ADDR
#define BMP280_REG_ID    0xD0
#define BMP280_REG_CTRL  0xF4
#define BMP280_REG_CONF  0xF5
#define BMP280_REG_DATA  0xF7
#define BMP280_REG_CALIB 0x88
#define AHT20_ADDR       0x38
#define AHT20_CMD_INIT   0xBE
#define AHT20_CMD_TRIG   0xAC

typedef struct {
    uint16_t dig_T1; int16_t dig_T2, dig_T3;
    uint16_t dig_P1; int16_t dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9;
} bmp280_calib_t;

static i2c_master_dev_handle_t s_bmp280 = NULL;
static i2c_master_dev_handle_t s_aht20  = NULL;
static bmp280_calib_t          s_calib  = {0};

static esp_err_t bmp_read(uint8_t reg, uint8_t *buf, size_t len) {
    return i2c_master_transmit_receive(s_bmp280, &reg, 1, buf, len, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
}
static esp_err_t bmp_write(uint8_t reg, uint8_t val) {
    uint8_t b[2] = {reg, val};
    return i2c_master_transmit(s_bmp280, b, 2, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
}

static bool sensor_init(void) {
    uint8_t id = 0;
    if (bmp_read(BMP280_REG_ID, &id, 1) != ESP_OK || (id != 0x58 && id != 0x60)) {
        ESP_LOGE(TAG, "BMP280 nicht gefunden (ID=0x%02x)", id); return false;
    }
    uint8_t cb[24]; bmp_read(BMP280_REG_CALIB, cb, 24);
    s_calib.dig_T1 = (uint16_t)(cb[1]<<8|cb[0]); s_calib.dig_T2 = (int16_t)(cb[3]<<8|cb[2]);
    s_calib.dig_T3 = (int16_t)(cb[5]<<8|cb[4]);  s_calib.dig_P1 = (uint16_t)(cb[7]<<8|cb[6]);
    s_calib.dig_P2 = (int16_t)(cb[9]<<8|cb[8]);  s_calib.dig_P3 = (int16_t)(cb[11]<<8|cb[10]);
    s_calib.dig_P4 = (int16_t)(cb[13]<<8|cb[12]); s_calib.dig_P5 = (int16_t)(cb[15]<<8|cb[14]);
    s_calib.dig_P6 = (int16_t)(cb[17]<<8|cb[16]); s_calib.dig_P7 = (int16_t)(cb[19]<<8|cb[18]);
    s_calib.dig_P8 = (int16_t)(cb[21]<<8|cb[20]); s_calib.dig_P9 = (int16_t)(cb[23]<<8|cb[22]);
    bmp_write(BMP280_REG_CTRL, 0x27);
    bmp_write(BMP280_REG_CONF, 0xA0);
    ESP_LOGI(TAG, "BMP280 gefunden (ID=0x%02x)", id);

    i2c_device_config_t aht_cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7,
                                     .device_address  = AHT20_ADDR, .scl_speed_hz = 100000 };
    if (i2c_master_bus_add_device(s_bus, &aht_cfg, &s_aht20) == ESP_OK) {
        uint8_t cmd[3] = {AHT20_CMD_INIT, 0x08, 0x00};
        if (i2c_master_transmit(s_aht20, cmd, 3, pdMS_TO_TICKS(I2C_TIMEOUT_MS)) == ESP_OK) {
            vTaskDelay(pdMS_TO_TICKS(10));
            ESP_LOGI(TAG, "AHT20 gefunden");
        } else {
            i2c_master_bus_rm_device(s_aht20); s_aht20 = NULL;
        }
    } else { s_aht20 = NULL; }
    return true;
}

static bool sensor_measure(hannah_sensor_data_t *out) {
    uint8_t raw[6];
    if (bmp_read(BMP280_REG_DATA, raw, 6) != ESP_OK) return false;
    int32_t adc_P = ((int32_t)raw[0]<<12)|((int32_t)raw[1]<<4)|(raw[2]>>4);
    int32_t adc_T = ((int32_t)raw[3]<<12)|((int32_t)raw[4]<<4)|(raw[5]>>4);
    int32_t v1 = ((((adc_T>>3)-((int32_t)s_calib.dig_T1<<1)))*(int32_t)s_calib.dig_T2)>>11;
    int32_t v2 = (((((adc_T>>4)-(int32_t)s_calib.dig_T1)*((adc_T>>4)-(int32_t)s_calib.dig_T1))>>12)*(int32_t)s_calib.dig_T3)>>14;
    int32_t t_fine = v1 + v2;
    out->temperature = (float)((t_fine*5+128)>>8)/100.0f;
    int64_t p1 = (int64_t)t_fine - 128000;
    int64_t p2 = p1*p1*(int64_t)s_calib.dig_P6; p2 += (p1*(int64_t)s_calib.dig_P5)<<17;
    p2 += ((int64_t)s_calib.dig_P4)<<35;
    p1  = ((p1*p1*(int64_t)s_calib.dig_P3)>>8)+((p1*(int64_t)s_calib.dig_P2)<<12);
    p1  = ((((int64_t)1<<47)+p1)*(int64_t)s_calib.dig_P1)>>33;
    if (p1 == 0) { out->pressure = 0; } else {
        int64_t p = 1048576 - adc_P;
        p = (((p<<31)-p2)*3125)/p1;
        p1 = ((int64_t)s_calib.dig_P9*(p>>13)*(p>>13))>>25;
        p2 = ((int64_t)s_calib.dig_P8*p)>>19;
        p  = ((p+p1+p2)>>8)+((int64_t)s_calib.dig_P7<<4);
        out->pressure = (float)p/25600.0f;
    }
    out->gas_resistance = NAN;
    if (s_aht20) {
        uint8_t trig[3] = {AHT20_CMD_TRIG, 0x33, 0x00};
        i2c_master_transmit(s_aht20, trig, 3, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
        vTaskDelay(pdMS_TO_TICKS(80));
        uint8_t h[6];
        if (i2c_master_receive(s_aht20, h, 6, pdMS_TO_TICKS(I2C_TIMEOUT_MS)) == ESP_OK && !(h[0]&0x80)) {
            uint32_t hraw = ((uint32_t)h[1]<<12)|((uint32_t)h[2]<<4)|(h[3]>>4);
            out->humidity = (float)hraw/1048576.0f*100.0f;
        } else { out->humidity = NAN; }
    } else { out->humidity = NAN; }
    return true;
}
#endif /* HANNAH_SENSOR_TYPE */

/* ========================================================================
 * Gemeinsamer Sensor-Task + öffentliche API
 * ======================================================================== */

static void sensor_task(void *arg)
{
    while (!s_ready) vTaskDelay(pdMS_TO_TICKS(100));
    while (1) {
        hannah_sensor_data_t data = {0};
        if (sensor_measure(&data)) {
            s_last     = data;
            s_has_data = true;

            if (!isnan(data.gas_resistance))
                ESP_LOGI(TAG, "T=%.1f°C  P=%.1f hPa  H=%.1f%%  Gas=%.0f Ω",
                         data.temperature, data.pressure, data.humidity, data.gas_resistance);
            else
                ESP_LOGI(TAG, "T=%.1f°C  P=%.1f hPa  H=%.1f%%",
                         data.temperature, data.pressure, data.humidity);

            const hannah_config_t *cfg = hannah_config_get();
            char topic[96];
            snprintf(topic, sizeof(topic), "hannah/satellite/%s/sensors", cfg->device_id);

            char payload[128];
            if (!isnan(data.gas_resistance))
                snprintf(payload, sizeof(payload),
                         "{\"temperature\":%.2f,\"pressure\":%.2f,\"humidity\":%.2f,\"gas_resistance\":%.0f}",
                         data.temperature, data.pressure, data.humidity, data.gas_resistance);
            else
                snprintf(payload, sizeof(payload),
                         "{\"temperature\":%.2f,\"pressure\":%.2f,\"humidity\":%.2f}",
                         data.temperature, data.pressure, data.humidity);

            hannah_net_mqtt_publish(topic, payload, 1, 1);
        }
        vTaskDelay(pdMS_TO_TICKS(30000));
    }
}

static void i2c_scan(void)
{
    ESP_LOGD(TAG, "I2C-Scan (SDA=%d SCL=%d):", CONFIG_HANNAH_SENSOR_SDA_GPIO, CONFIG_HANNAH_SENSOR_SCL_GPIO);
    for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
        i2c_master_dev_handle_t probe;
        i2c_device_config_t cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7,
                                    .device_address  = addr, .scl_speed_hz = 100000 };
        if (i2c_master_bus_add_device(s_bus, &cfg, &probe) == ESP_OK) {
            uint8_t dummy;
            if (i2c_master_receive(probe, &dummy, 1, pdMS_TO_TICKS(10)) == ESP_OK)
                ESP_LOGD(TAG, "  Gerät gefunden: 0x%02x", addr);
            i2c_master_bus_rm_device(probe);
        }
    }
}

void hannah_sensors_init(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port              = I2C_NUM_0,
        .sda_io_num            = CONFIG_HANNAH_SENSOR_SDA_GPIO,
        .scl_io_num            = CONFIG_HANNAH_SENSOR_SCL_GPIO,
        .clk_source            = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt     = 7,
        .flags.enable_internal_pullup = true,
    };
    if (i2c_new_master_bus(&bus_cfg, &s_bus) != ESP_OK) {
        ESP_LOGE(TAG, "I2C-Bus konnte nicht initialisiert werden"); return;
    }
    i2c_scan();

#if CONFIG_HANNAH_SENSOR_TYPE_BME680
    i2c_device_config_t dev_cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7,
                                     .device_address  = BME680_ADDR, .scl_speed_hz = 400000 };
    if (i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev) != ESP_OK) {
        ESP_LOGE(TAG, "BME680 konnte nicht zum I2C-Bus hinzugefügt werden"); return;
    }
#else
    i2c_device_config_t dev_cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7,
                                     .device_address  = BMP280_ADDR, .scl_speed_hz = 100000 };
    if (i2c_master_bus_add_device(s_bus, &dev_cfg, &s_bmp280) != ESP_OK) {
        ESP_LOGE(TAG, "BMP280 konnte nicht zum I2C-Bus hinzugefügt werden"); return;
    }
#endif

    s_ready = sensor_init();
    if (!s_ready) { ESP_LOGE(TAG, "Sensor-Initialisierung fehlgeschlagen"); return; }

    xTaskCreate(sensor_task, "sensors", 6144, NULL, 3, NULL);
    ESP_LOGI(TAG, "Sensor-Task gestartet (alle 30 s).");
}

bool hannah_sensors_get(hannah_sensor_data_t *out)
{
    if (!s_has_data) return false;
    *out = s_last;
    return true;
}
