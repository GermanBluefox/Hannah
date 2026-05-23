#pragma once
#include <stdint.h>
#include <stddef.h>

/**
 * hannah_audio — PDM Mic-Array, Speaker, Tasten
 *
 * Hardware (PCB Rev.3):
 *   Mic:     2× SPH0641LU4H-1 (PDM, CLK=GPIO39, DATA=GPIO40, SEL trennt L/R)
 *   Speaker: MAX98357A (I2S, BCLK=GPIO47, LRC=GPIO38, DATA=GPIO21)
 *   Tasten:  PTT (GPIO12), Mute (GPIO11), Vol+ (GPIO13), Vol- (GPIO14)
 *            alle active-low, interner Pull-up aktiviert
 *   HW-Mute: NPN-Transistor via GPIO10 (HIGH = Mics aktiv)
 *
 * Pipeline Phase 1:
 *   PDM-Read → bei PTT gedrückt: hannah_net_send_audio()
 *              bei PTT losgelassen: hannah_net_send_audio_end()
 *
 * Pipeline Phase 2:
 *   PDM-Read → ESP-SR AFE (Beamforming + AEC + VAD) →
 *   Wake-Word → Stream-Start → audio_end bei Stille
 *
 * TTS-Wiedergabe:
 *   hannah_audio_play() nimmt PCM-Chunks entgegen und schreibt sie
 *   asynchron über den Speaker-Task auf I2S.
 */

void hannah_audio_init(void);

/* TTS-PCM-Chunk zur Wiedergabe einreihen (thread-safe). */
void hannah_audio_play(const uint8_t *pcm, size_t len, int sample_rate);

/* TTS-Stream abgeschlossen — Speaker-Task spielt verbleibende Chunks ab. */
void hannah_audio_play_end(void);

/* Playback-Steuerung (stop/pause/resume via UDP-Control). */
void hannah_audio_stop(void);    /* Speaker-Queue leeren, Streaming stoppen. */
void hannah_audio_pause(void);   /* Mic-Streaming pausieren. */
void hannah_audio_resume(void);  /* Mic-Streaming fortsetzen. */
