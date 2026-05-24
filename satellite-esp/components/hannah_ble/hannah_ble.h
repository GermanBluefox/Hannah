#pragma once

/**
 * hannah_ble — passiver BLE-Scanner für Indoor-Lokalisierung
 *
 * Scannt BLE-Advertisements von konfigurierten MAC-Adressen (Watchlist)
 * und meldet RSSI per MQTT: hannah/satellite/{device}/ble/report
 *
 * Watchlist-Empfang via MQTT: hannah/satellite/{device}/ble/watchlist
 * Payload: {"macs": ["aa:bb:cc:dd:ee:ff", ...]}
 *
 * Report-Payload: {"mac":"aa:bb:cc:dd:ee:ff","rssi":-65}
 */

void hannah_ble_init(void);

/**
 * Aktualisiert die Watchlist anhand eines JSON-Strings.
 * Wird von hannah_net aufgerufen wenn eine neue Watchlist eintrifft.
 */
void hannah_ble_set_watchlist_json(const char *json, int len);
