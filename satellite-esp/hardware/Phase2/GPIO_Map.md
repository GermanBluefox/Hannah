# Hannah Satellite — GPIO Map

**Chip:** ESP32-S3-WROOM-1-N16R8  
**Board:** Rev.3 PCB, 88 mm rund

---

## Vollständige Pin-Tabelle

| GPIO | Net / Funktion    | Richtung | Beschreibung |
|-----:|-------------------|----------|--------------|
|  0   | Boot-Strapping    | —        | Tied to 3,3 V → immer Normal-Boot |
|  1   | NC                | —        | — |
|  2   | NC                | —        | — |
|  3   | NC                | —        | — |
|  4   | NC                | —        | — |
|  5   | LED_DATA          | Out      | SK6812MINI-E Ring (24 LEDs) via SN74AHCT125 Level-Shifter (5 V) |
|  6   | NC                | —        | — |
|  7   | NC                | —        | — |
|  8   | I2C_SDA           | I/O      | BME680 (Temperatur, Feuchte, Luftdruck) |
|  9   | I2C_SCL           | Out      | BME680 |
| 10   | MIC_MUTE          | Out      | NPN-Transistor: HIGH = Mics aktiv, LOW = Hardware-Stumm |
| 11   | IO_MUTE           | In       | Mute-Taste, active-low, interner Pull-up |
| 12   | IO_PTT            | In       | Push-to-Talk-Taste, active-low, interner Pull-up |
| 13   | IO_VOL+           | In       | Lauter-Taste, active-low, interner Pull-up |
| 14   | IO_VOL-           | In       | Leiser-Taste, active-low, interner Pull-up |
| 15   | LD2410_OUT        | In       | Digitales Präsenzsignal des LD2410 |
| 16   | LD2410_RX (UART2) | In       | UART2 RX — ESP empfängt von LD2410 TX |
| 17   | LD2410_TX (UART2) | Out      | UART2 TX — ESP sendet an LD2410 RX |
| 18   | STATUS_LED        | Out      | Einzel-Status-LED via R470 |
| 19   | USB_D−            | —        | USB-C D− (ROM-Bootloader, kein Firmware-Zugriff) |
| 20   | USB_D+            | —        | USB-C D+ (ROM-Bootloader, kein Firmware-Zugriff) |
| 21   | AMP_DATA          | Out      | MAX98357A I2S DIN (Audio-Daten) |
| 35   | ⚠ PSRAM           | —        | Intern mit PSRAM verbunden — nie verwenden |
| 36   | ⚠ PSRAM           | —        | Intern mit PSRAM verbunden — nie verwenden |
| 37   | ⚠ PSRAM           | —        | Intern mit PSRAM verbunden — nie verwenden |
| 38   | AMP_LRC           | Out      | MAX98357A I2S LRC / Word Select |
| 39   | MIC_CLOCK         | Out      | PDM Clock — beide SPH0641LU4H-1 teilen die Leitung |
| 40   | MIC_DATA          | In       | PDM Data — SEL-Pin bestimmt welcher Mic L/R antwortet |
| 41   | NC                | —        | — |
| 42   | NC                | —        | — |
| 43   | UART0_TXD         | Out      | Debug-Header (J4), ROM-Bootloader TX — Initial-Flashing |
| 44   | UART0_RXD         | In       | Debug-Header (J4), ROM-Bootloader RX — Initial-Flashing |
| 45   | NC                | —        | Strapping: NC = SPI-Boot (normal) |
| 46   | NC                | —        | Strapping: NC = normale Log-Ausgabe |
| 47   | AMP_BCLK          | Out      | MAX98357A I2S Bit Clock |
| 48   | NC                | —        | — |

---

## Funktionsgruppen

### I2C — BME680
| Signal | GPIO |
|--------|-----:|
| SDA    |  8   |
| SCL    |  9   |

### PDM-Mikrofone — 2× SPH0641LU4H-1
| Signal       | GPIO | Hinweis |
|--------------|-----:|---------|
| CLK          | 39   | Beide Mics teilen dieselbe Leitung |
| DATA         | 40   | Beide Mics teilen dieselbe Leitung |
| HW-Mute Out  | 10   | NPN-Transistor-Steuerung |

### I2S-Verstärker — MAX98357A
| Signal | GPIO |
|--------|-----:|
| BCLK   | 47   |
| LRC    | 38   |
| DATA   | 21   |

### Tasten (alle active-low, interner Pull-up)
| Taste  | GPIO |
|--------|-----:|
| Mute   | 11   |
| PTT    | 12   |
| Vol+   | 13   |
| Vol−   | 14   |

### LD2410 mmWave-Radar (UART2)
| Signal | GPIO |
|--------|-----:|
| OUT    | 15   |
| RX     | 16   |
| TX     | 17   |

### LEDs
| Signal           | GPIO | Hinweis |
|------------------|-----:|---------|
| SK6812-Ring      |  5   | Via SN74AHCT125 Level-Shifter (3,3 V → 5 V) |
| Status-LED       | 18   | Einzel-LED, via R470 |

### Debug / Flashing
| Signal    | GPIO | Hinweis |
|-----------|-----:|---------|
| UART0 TX  | 43   | J4 Debug-Header, 4-Pin 2,54 mm Right-Angle |
| UART0 RX  | 44   | J4 Debug-Header |
| USB D−    | 19   | Nur für OTA nach Initial-Flashing via UART0 |
| USB D+    | 20   | Nur für OTA nach Initial-Flashing via UART0 |
