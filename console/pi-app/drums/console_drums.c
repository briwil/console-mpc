/*
 * Console drum synth: the LXR's six drum voices (lxr/, from Erica Synths' LXR firmware, GPL-3.0),
 * run on the Pi. This file is the glue the console talks to (through ctypes, see drums.py):
 *
 *   drums_init()                       start the engine and load the LXR's Init Kit
 *   drums_set_param(i, v)              set kit parameter i (the LXR's own numbering, 0-based) to v (0-127)
 *   drums_get_param(i)                 read it back
 *   drums_trigger(lane, velocity)      hit a voice: lanes 0-2 drums, 3 snare, 4 cymbal, 5 hi-hat (6: open hat)
 *   drums_render(out, frames)          the next frames, one mono channel per voice: out[frame * 6 + voice], -1..1
 *   drums_pan(lane)                    the voice's pan in the kit, 0 (left) .. 127 (right)
 *
 * Parameters are the LXR's, plus Console's own after them: NOISE_DECAY (the snare noise's decay).
 *
 * Also here: stand-ins for the parts of the LXR firmware that aren't brought over (its sequencer,
 * menu, front panel, faders and MIDI output). Changes to the LXR's own code are marked "Console
 * change" there: Oscillator.c (overflow test in plain C), MidiParser.c (FINE spans a semitone each way)
 * and Snare.c/.h (the noise has its own decay).
 *
 * This file: GPL-3.0, like the code it links with.
 */
#include <string.h>
#include "stm32f7xx_hal.h"
#include "Soundengine/config.h"
#include "Soundengine/DSPAudio/DrumVoice.h"
#include "Soundengine/DSPAudio/Snare.h"
#include "Soundengine/DSPAudio/HiHat.h"
#include "Soundengine/DSPAudio/CymbalVoice.h"
#include "Soundengine/DSPAudio/lfo.h"
#include "Soundengine/DSPAudio/ResonantFilter.h"
#include "Soundengine/DSPAudio/modulationNode.h"
#include "Soundengine/DSPAudio/random.h"
#include "Soundengine/DSPAudio/mixer.h"
#include "Soundengine/MIDI/MidiMessages.h"
#include "Soundengine/MIDI/MidiParser.h"
#include "Soundengine/MIDI/ParameterArray.h"
#include "Soundengine/Sequencer/sequencer.h"
#include "Preset/InitKit.h"
#include "menu/menu.h"

#define VOICES 6
#define BLOCK OUTPUT_DMA_SIZE            /* the engine's own block size (64 frames) */

/* ------------------------------------------------------------------ stand-ins */

GPIO_TypeDef console_gpio = {0xffffffffu};
RNG_HandleTypeDef hrng;
DWT_Type console_dwt;
volatile uint32_t systick_ticks;
uint8_t activeParameters[NUM_PARAMS];
uint8_t menu_activePage;
uint8_t frontParser_activeTrack;
PatternSet seq_patternSet;
static uint16_t console_bpm = 120;

void uart_sendFrontpanelByte(uint8_t data) { (void)data; }
void uart_sendMidi(MidiMsg msg) { (void)msg; }
void usb_sendMidi(MidiMsg msg) { (void)msg; }
float adc_getFaderVolume(uint8_t idx) { (void)idx; return 1.0f; }   /* volume is the console's job */
uint8_t seq_getExtSync() { return 0; }
void seq_midiNoteOff(uint8_t chan) { (void)chan; }
void seq_setRunning(uint8_t isRunning) { (void)isRunning; }
void seq_setMute(uint8_t trackNr, uint8_t isMuted) { (void)trackNr; (void)isMuted; }
void seq_sendMidiNoteOn(const uint8_t channel, const uint8_t note, const uint8_t veloc) { (void)channel; (void)note; (void)veloc; }
uint8_t seq_isRunning() { return 1; }
void sync_midiStartStop(uint8_t isStart) { (void)isStart; }
void sync_midiResetPosition() {}
void seq_sync() {}
void seq_setNextPattern(const uint8_t patNr) { (void)patNr; }
void seq_recordAutomation(uint8_t voice, uint8_t dest, uint8_t value) { (void)voice; (void)dest; (void)value; }
uint8_t seq_isTrackMuted(uint8_t trackNr) { (void)trackNr; return 0; }
uint16_t seq_getBpm() { return console_bpm; }
void seq_addNote(uint8_t trackNr, uint8_t vel, uint8_t note) { (void)trackNr; (void)vel; (void)note; }
void menu_switchSubPage(uint8_t subPageNr, uint8_t toggle) { (void)subPageNr; (void)toggle; }
void menu_repaint() {}
uint8_t menu_getViewedPattern() { return 0; }
uint8_t menu_getSubPage() { return 0; }
uint8_t menu_getActiveVoice() { return 0; }

/* ------------------------------------------------------------------ the console's side */

extern const uint16_t console_modTargets[];
extern const int console_numModTargets;

static int16_t blockBuf[VOICES][BLOCK];
static uint8_t noParameter;
/* Console's own settings, numbered after the LXR's */
#define NOISE_DECAY END_OF_SOUND_PARAMETERS     /* the snare noise's decay (the tone's is PAR_VELOD4) */
#define PARAM_COUNT (END_OF_SOUND_PARAMETERS + 1)
static uint8_t consoleParameters[PARAM_COUNT - END_OF_SOUND_PARAMETERS];             /* what parameter 0 ("none") points at: the LXR leaves it pointing at address 0 */
static int blockPos = BLOCK;            /* frames of blockBuf already handed out */

static ModulationNode *lfoTarget(int voice)
{
	switch (voice) {
	case 0: case 1: case 2: return &voiceArray[voice].lfo.modTarget;
	case 3: return &snareVoice.lfo.modTarget;
	case 4: return &cymbalVoice.lfo.modTarget;
	default: return &hatVoice.lfo.modTarget;
	}
}

void drums_set_param(int index, int value)
{
	if (index < 0 || index >= PARAM_COUNT) return;
	if (value < 0) value = 0;
	if (value > 127) value = 127;
	if (index >= END_OF_SOUND_PARAMETERS) {
		consoleParameters[index - END_OF_SOUND_PARAMETERS] = (uint8_t)value;
		if (index == NOISE_DECAY)
			Snare_setNoiseDecay((uint8_t)value);
		return;
	}
	if ((index >= PAR_VEL_DEST_1 && index < PAR_VEL_DEST_1 + 6) || (index >= PAR_TARGET_LFO1 && index < PAR_TARGET_LFO1 + 6)) {
		/* a velocity or LFO destination: the kit stores an entry in the LXR's list of targets */
		if (value >= console_numModTargets) value = 0;
		activeParameters[index] = (uint8_t)value;
		if (index < PAR_VEL_DEST_1 + 6)
			modNode_setDestination(&velocityModulators[index - PAR_VEL_DEST_1], console_modTargets[value]);
		else
			modNode_setDestination(lfoTarget(index - PAR_TARGET_LFO1), console_modTargets[value]);
		return;
	}
	if (index >= PAR_VOICE_LFO1 && index < PAR_VOICE_LFO1 + 6 && (value < 1 || value > 6))
		value = 1;
	activeParameters[index] = (uint8_t)value;
	MidiMsg msg;
	if (index < 128) {                   /* what the LXR's front panel sends, as its sound board receives it */
		msg.status = MIDI_CC;
		msg.data1 = (uint8_t)((index + 1) & 0x7f);
	} else {
		msg.status = MIDI_CC2;
		msg.data1 = (uint8_t)(index - 128);
	}
	msg.data2 = (uint8_t)value;
	midiParser_ccHandler(msg, 1, 0, 0.f);
}

int drums_get_param(int index)
{
	if (index < 0 || index >= PARAM_COUNT) return -1;
	if (index >= END_OF_SOUND_PARAMETERS)
		return consoleParameters[index - END_OF_SOUND_PARAMETERS];
	return activeParameters[index];
}

int drums_param_count(void) { return PARAM_COUNT; }

/* load a kit: values[0..count-1] are the kit's parameters in the LXR's numbering */
void drums_load_kit(const uint8_t *values, int count)
{
	for (int i = 0; i < count && i < PARAM_COUNT; i++)
		drums_set_param(i, values[i]);
}

void drums_load_init_kit(void)
{
	drums_load_kit(initKit + 8, INIT_KIT_SIZE - 8);   /* the first 8 bytes are the kit's name */
	drums_set_param(NOISE_DECAY, initKit[8 + PAR_VELOD4]);  /* the noise starts as long as the tone */
}

int drums_init(void)
{
	initRng();
	mixer_init();
	parameterArray_init();
	parameterArray[0].ptr = &noParameter;
	parameterArray[0].type = TYPE_UINT8;
	for (int i = 0; i < 6; i++)
		modNode_init(&velocityModulators[i]);
	initDrumVoice();
	Snare_init();
	HiHat_init();
	Cymbal_init();
	drums_load_init_kit();
	blockPos = BLOCK;
	return BLOCK;
}

void drums_set_bpm(int bpm) { console_bpm = (uint16_t)(bpm > 0 ? bpm : 120); }

void drums_trigger(int lane, int velocity)
{
	if (velocity < 1) velocity = 1;
	if (velocity > 127) velocity = 127;
	const uint8_t note = 60;           /* the LXR plays each voice at its own pitch; 60 = no transpose */
	switch (lane) {
	case 0: case 1: case 2: Drum_trigger((uint8_t)lane, (uint8_t)velocity, note); break;
	case 3: Snare_trigger((uint8_t)velocity, note); break;
	case 4: Cymbal_trigger((uint8_t)velocity, note); break;
	case 5: HiHat_trigger((uint8_t)velocity, 0, note); break;   /* closed */
	case 6: HiHat_trigger((uint8_t)velocity, 1, note); break;   /* open */
	default: break;
	}
}

int drums_pan(int lane)
{
	switch (lane) {
	case 0: case 1: case 2: return voiceArray[lane].pan;
	case 3: return snareVoice.pan;
	case 4: return cymbalVoice.pan;
	case 5: return hatVoice.pan;
	default: return 64;
	}
}

static void render_block(void)
{
	/* the same steps, in the same order, as the LXR's mixer_calcNextSampleBlock(), minus its outputs */
	modNode_resetTargets();
	modNode_reassignVeloMod();
	lfo_dispatchNextValue(&voiceArray[0].lfo);
	lfo_dispatchNextValue(&voiceArray[1].lfo);
	lfo_dispatchNextValue(&voiceArray[2].lfo);
	lfo_dispatchNextValue(&snareVoice.lfo);
	lfo_dispatchNextValue(&cymbalVoice.lfo);
	lfo_dispatchNextValue(&hatVoice.lfo);
	SVF_recalcFreq(&voiceArray[0].filter);
	SVF_recalcFreq(&voiceArray[1].filter);
	SVF_recalcFreq(&voiceArray[2].filter);
	SVF_recalcFreq(&snareVoice.filter);
	SVF_recalcFreq(&cymbalVoice.filter);
	SVF_recalcFreq(&hatVoice.filter);
	calcDrumVoiceAsync(0);
	calcDrumVoiceAsync(1);
	calcDrumVoiceAsync(2);
	Snare_calcAsync();
	Cymbal_calcAsync();
	HiHat_calcAsync();
	calcDrumVoiceSyncBlock(0, blockBuf[0], BLOCK);
	calcDrumVoiceSyncBlock(1, blockBuf[1], BLOCK);
	calcDrumVoiceSyncBlock(2, blockBuf[2], BLOCK);
	Snare_calcSyncBlock(blockBuf[3], BLOCK);
	Cymbal_calcSyncBlock(blockBuf[4], BLOCK);
	HiHat_calcSyncBlock(blockBuf[5], BLOCK);
	systick_ticks += 1;
	blockPos = 0;
}

void drums_render(float *out, int frames)
{
	int done = 0;
	while (done < frames) {
		if (blockPos >= BLOCK)
			render_block();
		int n = BLOCK - blockPos;
		if (n > frames - done) n = frames - done;
		for (int i = 0; i < n; i++)
			for (int v = 0; v < VOICES; v++)
				out[(done + i) * VOICES + v] = blockBuf[v][blockPos + i] / 32768.0f;
		blockPos += n;
		done += n;
	}
}
