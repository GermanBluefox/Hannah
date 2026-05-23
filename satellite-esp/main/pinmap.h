#pragma once

/*
 * Hannah Satellite — GPIO Pin Map
 * Chip:   ESP32-S3-WROOM-1-N16R8
 * Board:  Rev.3 PCB, 88 mm rund
 *
 * Pins die per Kconfig konfigurierbar sind, stehen hier als Referenz.
 * Die tatsächlich genutzten Werte liefert CONFIG_HANNAH_*.
 */

/* ── I2C ─────────────────────────────────────────────────────────────────── */
#define PIN_I2C_SDA             8   /* BME680 (Temp/Feuchte/Luftdruck) */
#define PIN_I2C_SCL             9

/* ── PDM-Mikrofone (2× SPH0641LU4H-1) ───────────────────────────────────── */
#define PIN_MIC_CLK             39  /* PDM Clock — beide Mics teilen sich die Leitung */
#define PIN_MIC_DATA            40  /* PDM Data  — SEL-Pin bestimmt L/R-Kanal pro Mic */
#define PIN_MIC_MUTE_HW         10  /* NPN-Mute-Transistor: HIGH = aktiv, LOW = stumm */

/* ── I2S-Verstärker (MAX98357A) ──────────────────────────────────────────── */
#define PIN_AMP_BCLK            47  /* I2S Bit Clock */
#define PIN_AMP_LRC             38  /* I2S Word Select (LRC) */
#define PIN_AMP_DATA            21  /* I2S Audio Data (ESP DOUT → Amp DIN) */

/* ── LEDs ────────────────────────────────────────────────────────────────── */
#define PIN_LED_RING            5   /* SK6812MINI-E Ring (24 LEDs) via SN74AHCT125 (5 V) */
#define PIN_LED_STATUS          18  /* Einzel-Status-LED via R470 */

/* ── Tasten (active-low — internen Pull-up in gpio_config aktivieren) ────── */
#define PIN_BTN_MUTE            11  /* Mute */
#define PIN_BTN_PTT             12  /* Push-to-Talk */
#define PIN_BTN_VOL_UP          13  /* Lauter */
#define PIN_BTN_VOL_DOWN        14  /* Leiser */

/* ── LD2410 mmWave-Radar (UART2) ─────────────────────────────────────────── */
#define PIN_LD2410_OUT          15  /* Digitales Präsenzsignal (OUT-Pin des LD2410) */
#define PIN_LD2410_UART_RX      16  /* UART2 RX — ESP empfängt von LD2410 TX */
#define PIN_LD2410_UART_TX      17  /* UART2 TX — ESP sendet an LD2410 RX */

/* ── PSRAM (intern belegt — niemals als GPIO verwenden!) ────────────────── */
/* GPIO35, GPIO36, GPIO37 — intern mit dem PSRAM (N16R8) verdrahtet.
 * Zugriff von außen würde PSRAM korrumpieren.                              */

/* ── UART0 Debug-Header (Initial-Flashing, ROM-Bootloader) ──────────────── */
/* GPIO43 = TXD0, GPIO44 = RXD0 — werden vom ROM-Bootloader automatisch genutzt,
 * kein #define notwendig. 4-Pin Right-Angle Header auf B.Cu (Rev.3). */

/* ── Strapping-Pins ──────────────────────────────────────────────────────── */
/* GPIO0  → 3,3 V (Normal-Boot sichergestellt, kein externer Taster nötig) */
/* GPIO45 → NC  (Boot-Modus LOW = SPI-Boot, NC = floating-low = SPI-Boot) */
/* GPIO46 → NC  (Log-Level-Strapping, NC = normal logging) */
