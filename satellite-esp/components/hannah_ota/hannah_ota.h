#pragma once

/* OTA-Poll-Task starten und ota/ok-Callback registrieren.
 * Muss nach hannah_net_init() aufgerufen werden. */
void hannah_ota_init(void);
