#!/usr/bin/env python3
"""Console's own presets for synths that come with none (Plaits, Maze Voice): starting points to curate.
(Plaits' FM and 6-OP engines run at full level and clip in this build, so none of these use them.)

    python3 presets/make_presets.py          writes presets/<synth>/<name>.json (the format Menu > SAVE PRESET
                                             writes), and prints how each sounds by the numbers

Each preset is the module's own settings by name, in its own units; the module turns them into the knob
positions a saved preset keeps. The PRESETS page lists these after the synth's own (marked +).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "schwung"), os.path.join(HERE, "..")]

# name: ({setting: value}, reverb send, delay send)   (values as the synth shows them: 0-1 for Plaits)
DESIGNS = {
    "plaits": {
        "Round Bass":     ({"engine": "VA VCF", "harmonics": 0.15, "timbre": 0.28, "morph": 0.25, "decay": 0.55, "lpg_colour": 0.2}, 0, 0),
        "Squelch Bass":   ({"engine": "VA VCF", "harmonics": 0.3, "timbre": 0.5, "morph": 0.75, "decay": 0.35, "lpg_colour": 0.0, "velocity_sensitivity": 0.8}, 0, 10),
        "Soft Chords":    ({"engine": "Chord", "harmonics": 0.35, "timbre": 0.45, "morph": 0.3, "decay": 0.9, "attack": 0.45, "lpg_colour": 0.6}, 45, 0),
        "Glass Bell":     ({"engine": "Modal", "harmonics": 0.7, "timbre": 0.7, "morph": 0.3, "decay": 0.75, "lpg_colour": 0.9}, 35, 15),
        "Mellow Keys":    ({"engine": "V. Analog", "harmonics": 0.1, "timbre": 0.3, "morph": 0.2, "decay": 0.6, "lpg_colour": 0.8, "velocity_sensitivity": 0.9}, 20, 0),
        "Nylon Pluck":    ({"engine": "String", "harmonics": 0.35, "timbre": 0.7, "morph": 0.65, "decay": 0.65, "lpg_colour": 0.8}, 20, 0),
        "Wood Marimba":   ({"engine": "Modal", "harmonics": 0.3, "timbre": 0.4, "morph": 0.45, "decay": 0.6, "lpg_colour": 0.6}, 25, 0),
        "Drawbar Organ":  ({"engine": "Additive", "harmonics": 0.2, "timbre": 0.35, "morph": 0.25, "decay": 1.0, "lpg_colour": 1.0}, 25, 0),
        "Chip Lead":      ({"engine": "Chiptune", "harmonics": 0.3, "timbre": 0.4, "morph": 0.5, "decay": 0.55, "lpg_colour": 0.1, "velocity_sensitivity": 0.9}, 0, 25),
        "Wavetable Drift": ({"engine": "Wavetable", "harmonics": 0.5, "timbre": 0.3, "morph": 0.6, "morph_mod": 0.3, "decay": 0.85, "lpg_colour": 0.5}, 30, 20),
        "Robot Choir":    ({"engine": "Speech", "harmonics": 0.3, "timbre": 0.55, "morph": 0.2, "decay": 0.85, "attack": 0.3, "lpg_colour": 0.7}, 40, 0),
        "Swarm Pad":      ({"engine": "Swarm", "harmonics": 0.4, "timbre": 0.35, "morph": 0.3, "decay": 0.95, "attack": 0.6, "lpg_colour": 0.8}, 50, 0),
    },
    "maze": {
        "Bongo LPG":      ({"fold_drive": 15, "env1_decay": 32, "cutoff": 35, "cutoff_eg1": 60, "reso": 25, "rnd_voice": "OFF"}, 15, 0),
        "Folded Bass":    ({"vco_tune": -12, "fold_drive": 25, "fold_eg1": 20, "cutoff": 22, "cutoff_eg1": 35, "env1_decay": 50, "sat": 30, "rnd_voice": "OFF"}, 0, 0),
        "West Coast Lead": ({"fold_drive": 55, "fold_eg1": 40, "fm_depth": 18, "env1_decay": 70, "cutoff": 70, "cutoff_eg1": 25}, 20, 25),
        "Metal Bell":     ({"fm_depth": 60, "mod_freq": 700, "ring_lvl": 40, "env1_decay": 80, "cutoff": 85, "cutoff_eg1": 10}, 35, 10),
        "Breath Pad":     ({"noise_lvl": 12, "noise_tone": -30, "env1_decay": 95, "env2_decay": 95, "cutoff": 38, "reso": 30, "fold_drive": 10}, 50, 0),
        "Plucked Wire":   ({"fold_drive": 20, "fm_depth": 15, "env1_decay": 25, "cutoff": 20, "cutoff_eg1": 80, "reso": 35}, 25, 15),
        "Growl":          ({"fm_depth": 45, "mod_freq": 30, "fold_drive": 60, "filt_drive": 50, "cutoff": 60, "env1_decay": 60}, 0, 0),
        "Soft Keys":      ({"fold_drive": 8, "cutoff": 45, "cutoff_eg1": 35, "env1_decay": 55, "level": 85}, 25, 0),
    },
}


def kit_values(m, settings, rev, dly):
    vals = list(m.values)
    for key, v in settings.items():
        i = m.index[key]
        p = m.params[i]
        if p["kind"] == "menu":
            opts = [str(o).upper() for o in p["raw"]]
            vals[i] = opts.index(str(v).upper())
        else:
            vals[i] = m._position(i, str(v))
    return vals + [m.SENDS_MARK, rev, dly]


def measure(m, kit):
    """How it sounds by the numbers: loudness (RMS), peak, brightness (spectral centroid, Hz)."""
    import numpy as np
    m.load_kit(kit)
    m.render(512)
    out = []
    for nt in (48, 55, 60):
        m.note_on(nt, 100)
    for _ in range(20):
        s, l = m.render(2048)
        out.append(s[:, :2] + l[:, :2])
    for nt in (48, 55, 60):
        m.note_off(nt)
    for _ in range(10):
        s, l = m.render(2048)
        out.append(s[:, :2] + l[:, :2])
    m.all_off()
    m.render(2048)
    x = np.concatenate(out).mean(axis=1)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / 44100)
    return float(np.sqrt(np.mean(x ** 2))), float(np.max(np.abs(x))), float((spec * f).sum() / max(1e-9, spec.sum()))


def main():
    import modules as M
    for mid, designs in DESIGNS.items():
        m = M.make(mid)
        init = list(m.values)
        folder = os.path.join(HERE, mid)
        os.makedirs(folder, exist_ok=True)
        for name, (settings, rev, dly) in designs.items():
            m.load_kit(init + [m.SENDS_MARK, 0, 0])
            kit = kit_values(m, settings, rev, dly)
            rms, peak, bright = measure(m, kit)
            with open(os.path.join(folder, name + ".json"), "w") as f:
                json.dump({"name": name, "machine": mid, "values": kit}, f)
            print("%-7s %-16s loud %.3f  peak %.2f  bright %5.0f Hz%s" % (
                mid, name, rms, peak, bright, "   <- CHECK" if rms < 0.003 or peak > 1.2 else ""))


if __name__ == "__main__":
    main()
