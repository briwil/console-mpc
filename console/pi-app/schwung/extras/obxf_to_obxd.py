#!/usr/bin/env python3
"""Turn OB-Xf patches (.fxp, the Surge Synth Team's successor to OB-Xd; its factory patches are CC0) into
OB-Xd banks (.fxb) the OB-Xd module reads: a bank per group of categories, 128 programs at most.

    python3 obxf_to_obxd.py <OB-Xf Patches folder> <factory.fxb> <out folder>

OB-Xf grew out of OB-Xd, so most settings are the same, with the same 0-1 scaling (checked against both
sources): the oscillators, mixer, filter, envelopes, LFO 1, unison, portamento, voice drift. A patch that
leans on something OB-Xd hasn't got (the second LFO, ring mod, the Xpander filter modes, the LFO on the
volume) is left out, so what's kept sounds as it was meant to. Settings OB-Xd has and OB-Xf hasn't keep
their values from the factory bank's first program.
"""
import glob
import os
import re
import sys

# OB-Xd's settings, in its order (Engine/ParamsEnum.h)
OBXD = ("UNDEFINED MIDILEARN VOLUME VOICE_COUNT TUNE OCTAVE BENDRANGE BENDOSC2 LEGATOMODE BENDLFORATE VFLTENV "
        "VAMPENV ASPLAYEDALLOCATION PORTAMENTO UNISON UDET OSC2_DET LFOFREQ LFOSINWAVE LFOSQUAREWAVE LFOSHWAVE "
        "LFO1AMT LFO2AMT LFOOSC1 LFOOSC2 LFOFILTER LFOPW1 LFOPW2 OSC2HS XMOD OSC1P OSC2P OSCQuantize OSC1Saw "
        "OSC1Pul OSC2Saw OSC2Pul PW BRIGHTNESS ENVPITCH OSC1MIX OSC2MIX NOISEMIX FLT_KF CUTOFF RESONANCE "
        "MULTIMODE FILTER_WARM BANDPASS FOURPOLE ENVELOPE_AMT LATK LDEC LSUS LREL FATK FDEC FSUS FREL ENVDER "
        "FILTERDER PORTADER PAN1 PAN2 PAN3 PAN4 PAN5 PAN6 PAN7 PAN8 UNLEARN ECONOMY_MODE LFO_SYNC PW_ENV "
        "PW_ENV_BOTH ENV_PITCH_BOTH FENV_INVERT PW_OSC2_OFS LEVEL_DIF SELF_OSC_PUSH").split()
IX = {n: i for i, n in enumerate(OBXD)}

SAME = {   # OB-Xf name -> OB-Xd setting, the same value
    "Volume": "VOLUME", "Polyphony": "VOICE_COUNT", "Tune": "TUNE", "Transpose": "OCTAVE",
    "BendOsc2Only": "BENDOSC2", "EnvLegatoMode": "LEGATOMODE", "VibratoRate": "BENDLFORATE",
    "VelToFilterEnv": "VFLTENV", "VelToAmpEnv": "VAMPENV", "Portamento": "PORTAMENTO", "Unison": "UNISON",
    "UnisonDetune": "UDET", "Osc2Detune": "OSC2_DET", "LFO1Rate": "LFOFREQ", "LFO1ModAmount1": "LFO1AMT",
    "LFO1ModAmount2": "LFO2AMT", "OscSync": "OSC2HS", "OscCrossmod": "XMOD", "Osc1Pitch": "OSC1P",
    "Osc2Pitch": "OSC2P", "Osc1SawWave": "OSC1Saw", "Osc1PulseWave": "OSC1Pul", "Osc2SawWave": "OSC2Saw",
    "Osc2PulseWave": "OSC2Pul", "OscPW": "PW", "OscBrightness": "BRIGHTNESS", "EnvToPitchAmount": "ENVPITCH",
    "Osc1Mix": "OSC1MIX", "Osc2Mix": "OSC2MIX", "NoiseMix": "NOISEMIX", "FilterKeyFollow": "FLT_KF",
    "FilterCutoff": "CUTOFF", "FilterResonance": "RESONANCE", "FilterMode": "MULTIMODE",
    "Filter2PoleBPBlend": "BANDPASS", "Filter4PoleMode": "FOURPOLE", "FilterEnvAmount": "ENVELOPE_AMT",
    "AmpEnvAttack": "LATK", "AmpEnvDecay": "LDEC", "AmpEnvSustain": "LSUS", "AmpEnvRelease": "LREL",
    "FilterEnvAttack": "FATK", "FilterEnvDecay": "FDEC", "FilterEnvSustain": "FSUS", "FilterEnvRelease": "FREL",
    "EnvelopeSlop": "ENVDER", "FilterSlop": "FILTERDER", "PortamentoSlop": "PORTADER",
    "LFO1TempoSync": "LFO_SYNC", "EnvToPWAmount": "PW_ENV", "EnvToPWBothOscs": "PW_ENV_BOTH",
    "EnvToPitchBothOscs": "ENV_PITCH_BOTH", "FilterEnvInvert": "FENV_INVERT", "Osc2PWOffset": "PW_OSC2_OFS",
    "LevelSlop": "LEVEL_DIF", "Filter2PolePush": "SELF_OSC_PUSH",
}
SAME.update({"PanVoice%d" % i: "PAN%d" % i for i in range(1, 9)})
ROUTES = {"LFO1ToOsc1Pitch": "LFOOSC1", "LFO1ToOsc2Pitch": "LFOOSC2", "LFO1ToFilterCutoff": "LFOFILTER",
          "LFO1ToOsc1PW": "LFOPW1", "LFO1ToOsc2PW": "LFOPW2"}       # off / on / inverted: OB-Xd has on / off

# the banks: OB-Xf's categories, grouped (128 programs at most a bank)
BANKS = [("Xf Bass", ["Basses"]), ("Xf Leads", ["Leads"]), ("Xf Pads", ["Pads", "Strings", "Voices"]),
         ("Xf Keys", ["Keys", "Organs", "Mallets", "Bells", "Plucks", "Guitars"]),
         ("Xf Brass FX", ["Brass", "Winds", "FX", "Drums", "Percussion"]), ("Xf Atmos", ["Atmospheres", "Soundscapes"])]


def attrs(path):
    s = open(path, "rb").read().decode("latin1")
    x = s[s.index("<?xml"):]
    return {k: v for k, v in re.findall(r'(\w+)="([^"]*)"', x)}


def num(d, k, default=0.0):
    try:
        return float(d.get(k, default))
    except ValueError:
        return default


def why_not(d):
    """What OB-Xd can't do that this patch uses (None: it converts)."""
    if num(d, "RingModMix") > 0.02:
        return "ring mod"
    if num(d, "Filter4PoleXpander") > 0.5 and num(d, "Filter4PoleMode") > 0.5:
        return "xpander filter"
    if num(d, "LFO1ToVolume") > 0.25 and num(d, "LFO1ModAmount2") > 0.02:
        return "LFO to volume"
    lfo2 = any(num(d, "LFO2To" + t) > 0.25 for t in ("Osc1Pitch", "Osc2Pitch", "FilterCutoff", "Osc1PW", "Osc2PW", "Volume"))
    if lfo2 and (num(d, "LFO2ModAmount1") > 0.02 or num(d, "LFO2ModAmount2") > 0.02):
        return "second LFO"
    w2 = num(d, "LFO1Wave2", 0.5)
    routed = any(num(d, k) > 0.25 for k in ROUTES)
    if routed and w2 > 0.6 and abs(num(d, "LFO1Wave1", 0.5) - 0.5) < 0.1:
        return "saw LFO"
    return None


def convert(d, base):
    v = list(base)
    for xf, xd in SAME.items():
        if xf in d:
            v[IX[xd]] = num(d, xf)
    for xf, xd in ROUTES.items():
        v[IX[xd]] = 1.0 if num(d, xf) > 0.25 else 0.0
    # the LFO's waves: OB-Xf blends two shapes each way of the middle (0.5: off); OB-Xd switches
    v[IX["LFOSINWAVE"]] = 1.0 if abs(num(d, "LFO1Wave1", 0.5) - 0.5) > 0.1 else 0.0
    v[IX["LFOSQUAREWAVE"]] = 1.0 if num(d, "LFO1Wave2", 0.5) < 0.4 else 0.0
    v[IX["LFOSHWAVE"]] = 1.0 if abs(num(d, "LFO1Wave3", 0.5) - 0.5) > 0.1 else 0.0
    # pitch bend: OB-Xd has 2 or 12 semitones
    v[IX["BENDRANGE"]] = 1.0 if num(d, "PitchBendUp", 0.0) * 24 >= 7 else 0.0
    v[IX["ASPLAYEDALLOCATION"]] = 0.0
    v[IX["VOICE_COUNT"]] = min(v[IX["VOICE_COUNT"]], 7 / 31.0)    # (the Move: 8 voices at most)
    return v


def fxb(programs, current=0):
    """An OB-Xd bank: its header, then the XML it reads."""
    body = ['<?xml version="1.0" encoding="UTF-8"?> <discoDSP currentProgram="%d" midiChannel="0"><programs>' % current]
    for name, vals in programs:
        name = name.replace("&", "and").replace('"', "'").replace("<", "").replace(">", "")
        attrs_ = " ".join('Val_%d="%s"' % (i, repr(float(x))) for i, x in enumerate(vals))
        body.append('<program programName="%s" isDefault="0" voiceCount="8" %s/>' % (name, attrs_))
    body.append("</programs></discoDSP>")
    xml = "".join(body).encode("utf-8") + b"\0"
    chunk = b"CcnK" + (len(xml) + 152).to_bytes(4, "big") + b"FBCh" + (1).to_bytes(4, "big") + b"Obxd" + \
        (1).to_bytes(4, "big") + len(programs).to_bytes(4, "big") + b"\0" * 128 + len(xml).to_bytes(4, "big")
    return chunk + xml


def main():
    src, factory, out = sys.argv[1:4]
    base_attrs = re.search(r"<program [^>]*>", open(factory, "rb").read().decode("latin1")).group(0)
    base = [0.0] * len(OBXD)
    for k, x in re.findall(r'Val_(\d+)="([^"]*)"', base_attrs):
        if int(k) < len(base):
            base[int(k)] = float(x)
    os.makedirs(out, exist_ok=True)
    skipped = {}
    for bank, cats in BANKS:
        progs = []
        for cat in cats:
            for f in sorted(glob.glob(os.path.join(src, cat, "*.fxp"))):
                d = attrs(f)
                why = why_not(d)
                if why:
                    skipped[why] = skipped.get(why, 0) + 1
                    continue
                progs.append((d.get("programName") or os.path.splitext(os.path.basename(f))[0], convert(d, base)))
        progs = progs[:128]
        with open(os.path.join(out, bank + ".fxb"), "wb") as fh:
            fh.write(fxb(progs))
        print("%-12s %3d programs" % (bank, len(progs)))
    print("left out:", skipped)


if __name__ == "__main__":
    main()
