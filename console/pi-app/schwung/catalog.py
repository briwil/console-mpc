"""The Schwung sound generators Console can use: where each one's code is, the exact version, and how to
compile it on the Pi (from its own build script, without the Move's cross-compiler or Docker).

kind: "drums" (16 pads on MIDI notes 36-51, like a Move drum rack; the drum sequencer plays them) or
"synth" (played with notes). {out} is where the build writes dsp.so.
"""
import hashlib
import json

FIRST_PAD = 36                       # a Move drum rack: pad 1 is note 36 ... pad 16 note 51

MODULES = [
    # ---------------------------------------------------------------- drum machines
    {"id": "forge", "title": "FORGE", "kind": "drums", "license": "MIT",
     "repo": "filliformes/forge-move", "commit": "fc69e18d24035764bb0cb58b066d50b25baa7d3c",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "-o", "{out}", "src/dsp/forge.c",
                "-lm", "-lpthread"]]},
    {"id": "weirddreams", "title": "WEIRD DREAMS", "kind": "drums", "license": "MIT",
     "repo": "filliformes/weird-dreams-move", "commit": "eabd121d1ffd5d98c077633edeb18df90f85124b",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "-o", "{out}",
                "src/dsp/weird_dreams.c", "-lm", "-lpthread"]]},
    {"id": "libpo32", "title": "LIBPO32", "kind": "drums", "license": "none stated",
     "repo": "mestela/schwung-libpo32", "commit": "4125e2989df1747a66f56388eb0b5bd7e1310079",
     "json": "src/module.json", "files": ["src/kits"],
     "build": [["gcc", "-O3", "-ffast-math", "-shared", "-fPIC", "-w", "-DNDEBUG", "-Isrc/dsp",
                "src/dsp/po32_drum.c", "src/dsp/po32.c", "src/dsp/po32_synth.c",
                "src/dsp/po32_patch_import.c", "-o", "{out}", "-lm", "-lpthread"]]},
    {"id": "cw78", "title": "CW-78", "kind": "drums", "license": "GPL-3.0",
     "repo": "athousanddetails/schwung-cw-78", "commit": "108bae6924f2dc153003b573373bf874faf19953",
     "json": "src/module.json", "lanes": 14,
     "voice_prefixes": ["bd", "sd", "rs", "hh", "cy", "ma", "cl", "hb", "lb", "lc", "cb", "tb", "gu", "mb"],
     "pads": ["Bass Drum", "Snare", "Rimshot", "Hi-Hat", "Cymbal", "Maracas", "Claves", "Hi Bongo",
              "Lo Bongo", "Lo Conga", "Cowbell", "Tambourine", "Guiro", "Metal Beat"],
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "-Isrc", "-Isrc/dsp", "-Isrc/host",
                "src/dsp/cr78_plugin.cpp", "src/dsp/cr78_engine.cpp", "-o", "{out}", "-lm"]]},
    {"id": "simian", "title": "SIMIAN", "kind": "drums", "license": "GPL-3.0",
     "repo": "legsmechanical/schwung-simian", "commit": "647c2bb8b867e922f5240dec4b40a513cbb61b9e",
     "json": "src/module.json",
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "-Wno-comment", "-Isrc/dsp",
                "src/dsp/simian_plugin.cpp", "-o", "{out}", "-lm"]]},
    # ---------------------------------------------------------------- synths
    {"id": "obxd", "title": "OB-XD", "kind": "synth", "license": "GPL-3.0",
     "repo": "charlesvestal/schwung-obxd", "commit": "f02973f4075a86ab811b7193cc1ba9bdd58273f4",
     "json": "src/module.json", "files": ["src/presets"],
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "src/dsp/obxd_plugin.cpp", "-Isrc/dsp",
                "-o", "{out}", "-lm"]]},
    {"id": "dexed", "title": "DEXED", "kind": "synth", "license": "GPL-3.0",
     "repo": "charlesvestal/schwung-dx7", "commit": "07f7fed47c0ab4f706c7eb8a165d680c0cf1ee26",
     "json": "src/module.json", "files": ["banks"],
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "src/dsp/dx7_plugin.cpp",
                "src/dsp/msfa/dx7note.cc", "src/dsp/msfa/env.cc", "src/dsp/msfa/exp2.cc", "src/dsp/msfa/fm_core.cc",
                "src/dsp/msfa/fm_op_kernel.cc", "src/dsp/msfa/freqlut.cc", "src/dsp/msfa/lfo.cc",
                "src/dsp/msfa/pitchenv.cc", "src/dsp/msfa/sin.cc", "src/dsp/msfa/porta.cpp", "-Isrc/dsp",
                "-o", "{out}", "-lm"]]},
    {"id": "braids", "title": "BRAIDS", "kind": "synth", "license": "MIT",
     "repo": "charlesvestal/schwung-braids", "commit": "5920d30ca5510e5f17cd8b2437dfb8602e0f68a1",
     "json": "src/module.json", "files": ["src/presets"],
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "-DTEST", "-Isrc/dsp",
                "src/dsp/braids_plugin.cpp", "src/dsp/braids/macro_oscillator.cc",
                "src/dsp/braids/analog_oscillator.cc", "src/dsp/braids/digital_oscillator.cc",
                "src/dsp/braids/resources.cc", "src/dsp/braids/quantizer.cc", "src/dsp/stmlib/utils/random.cc",
                "-o", "{out}", "-lm"]]},
    {"id": "hush1", "title": "HUSH ONE", "kind": "synth", "license": "MIT",
     "repo": "charlesvestal/schwung-hush1", "commit": "598ab90505f7f924d09ed83f47e46430218cd43b",
     "json": "src/module.json",
     "build": [["gcc", "-std=c11", "-O3", "-shared", "-fPIC", "-w", "src/dsp/sh101_plugin.c",
                "src/dsp/sh101_control.c", "src/dsp/sh101_osc.c", "src/dsp/sh101_env.c", "src/dsp/sh101_filter.c",
                "src/dsp/sh101_lfo.c", "-Isrc", "-Isrc/dsp", "-o", "{out}", "-lm"]]},
    {"id": "raffo", "title": "RAFFOSYNTH", "kind": "synth", "license": "MIT",
     "repo": "charlesvestal/schwung-moog", "commit": "4f1f658c35a13a5786f13d31a77aba67312ca0dd",
     "json": "src/module.json",
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "src/dsp/moog_plugin.cpp",
                "src/dsp/moog_engine.c", "-Isrc/dsp", "-o", "{out}", "-lm"]]},
    {"id": "hera", "title": "HERA", "kind": "synth", "license": "GPL-3.0",
     "repo": "charlesvestal/schwung-hera", "commit": "7bcf8b8a0b4228daa3ef57ac095a6e6cf9a935e7",
     "json": "src/module.json", "files": ["src/presets"],
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "src/dsp/hera_plugin.cpp",
                "src/dsp/Engine/HeraEnvelope.cpp", "src/dsp/Engine/HeraLFO.cpp",
                "src/dsp/Engine/HeraLFOWithEnvelope.cpp", "src/dsp/Engine/HeraTables.cpp",
                "src/dsp/Engine/bbd_line.cpp", "src/dsp/Engine/bbd_filter.cpp", "-Isrc/dsp", "-Isrc/dsp/Engine",
                "-o", "{out}", "-lm"]]},
    {"id": "plaits", "title": "PLAITS", "kind": "synth", "license": "MIT",
     "repo": "j3threejay/move-anything-plaits", "commit": "6d2ab081ac729acd254f5eec66a11c3fca8910d4",
     "json": "src/module.json",
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "-DTEST", "-Isrc", "-Isrc/dsp",
                "-Isrc/dsp/plaits", "-Isrc/dsp/stmlib", "src/dsp/plaits/dsp/chords/chord_bank.cc",
                "src/dsp/plaits/dsp/engine/*.cc", "src/dsp/plaits/dsp/engine2/*.cc", "src/dsp/plaits/dsp/fm/*.cc",
                "src/dsp/plaits/dsp/physical_modelling/*.cc", "src/dsp/plaits/dsp/speech/*.cc",
                "src/dsp/plaits/dsp/voice.cc", "src/dsp/plaits/resources.cc", "src/dsp/stmlib/dsp/atan.cc",
                "src/dsp/stmlib/dsp/units.cc", "src/dsp/stmlib/utils/random.cc", "src/dsp/plaits_plugin.cpp",
                "-o", "{out}", "-lm"]],
     # the 6-op FM engines' pitch could run away (to 1e13 semitones) and this loop then never ended: Console froze
     # (found by move/fxprobe.py instruments). Now an impossible pitch is held at the ends.
     "patches": [["src/dsp/stmlib/dsp/units.h",
                  "inline float SemitonesToRatioSafe(float semitones) {\n  float scale = 1.0f;\n",
                  "inline float SemitonesToRatioSafe(float semitones) {\n  float scale = 1.0f;\n"
                  "  if (!(semitones > -1200.0f)) semitones = -1200.0f;   /* (Console: also NaN) */\n"
                  "  if (semitones > 1200.0f) semitones = 1200.0f;\n"],
                 # ... and its patch could come out damaged, sending it to a missing algorithm (a crash):
                 # held to the 32 there are
                 ["src/dsp/plaits/dsp/fm/voice.h",
                  "algorithms_->is_modulator(patch_->algorithm, i)",
                  "algorithms_->is_modulator(patch_->algorithm & 31, i)"],
                 ["src/dsp/plaits/dsp/fm/voice.h",
                  "          algorithms_->render_call(patch_->algorithm, i);\n",
                  "          algorithms_->render_call(patch_->algorithm & 31, i);\n"
                  "      if (!call.render_fn || call.n <= 0) break;   /* (Console) */\n"]]},
    {"id": "essaim", "title": "ESSAIM", "kind": "synth", "license": "MIT",
     "repo": "filliformes/essaim-move", "commit": "22f63b7776b15400458656697aeae88527b9d910",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "src/dsp/essaim.c", "-o", "{out}", "-lm"]]},
    {"id": "denis", "title": "DENIS", "kind": "synth", "license": "MIT",
     "repo": "filliformes/denis-move", "commit": "da7fb7fe095f07aeda6e6056fb78d361c68862df",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "src/dsp/denis.c", "-o", "{out}", "-lm"]]},
    {"id": "wurl", "title": "WURL", "kind": "synth", "license": "GPL-3.0",
     "repo": "filliformes/wurl-move", "commit": "2d5b77dd7431d2545adf8f4af1fb5260c30120bf",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "src/dsp/wurl.c", "-o", "{out}", "-lm"]]},
    {"id": "aphex", "title": "APHEX", "kind": "synth", "license": "MIT",
     "repo": "filliformes/aphex-move", "commit": "9246640895e51d24b2335e0e564d4e5e941f4a5a",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "-Isrc/dsp", "src/dsp/aphex.c", "-o", "{out}",
                "-lm"]]},
    {"id": "fizzik", "title": "FIZZIK", "kind": "synth", "license": "MIT",
     "repo": "filliformes/fizzik-move", "commit": "1af291e2fb83477b64dca807430d860a81ce6cc6",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "src/dsp/fizzik.c", "-o", "{out}", "-lm"]]},
    {"id": "maze", "title": "MAZE VOICE", "kind": "synth", "license": "MIT",
     "repo": "sd88me/schwung-maze", "commit": "e774a674eef281248282ab47f69a9456bf6631fc",
     "json": "src/maze-voice/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "-fvisibility=hidden", "-DOVERSAMPLE=2",
                "-Isrc/include", "src/maze-voice/dsp/maze_voice.c", "-o", "{out}", "-lm"]]},
    {"id": "quilt", "title": "QUILT", "kind": "synth", "license": "PolyForm Strict 1.0.0",
     "repo": "kliegsablaze/quilt", "commit": "cb0e91b9988b2f7ae0b3ba7b9b224c14f0f07927",
     "json": "src/module.json",
     "build": [["gcc", "-std=c11", "-O2", "-shared", "-fPIC", "-w", "-Isrc/dsp", "src/dsp/*.c", "-o", "{out}",
                "-lm"]]},
    {"id": "chonk", "title": "CHONK", "kind": "synth", "license": "GPL-3.0",
     "repo": "legsmechanical/schwung-chonk", "commit": "da41ad0a3662094b06418711e00972ff1b41800e",
     "json": "src/module.json", "files": ["src/presets"],
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "-Wno-comment", "src/dsp/chonk_plugin.cpp",
                "-Isrc/dsp", "-o", "{out}", "-lm"]]},
    {"id": "tinyk", "title": "TINYK", "kind": "synth", "license": "MIT",
     "repo": "fleshinachair/TinyK", "commit": "032a8757022f99e84e1053d8f5fe499909e28ae7",
     "json": "src/module.json", "files": ["src/presets.json", "src/presets.h"],
     "build": [["gcc", "-O3", "-shared", "-fPIC", "-w", "-Isrc", "-Isrc/dsp", "src/dsp/dsp.c", "-o", "{out}",
                "-lm"]]},
    {"id": "tinypro5", "title": "TINYPRO5", "kind": "synth", "license": "MIT",
     "repo": "fleshinachair/TinyPro5", "commit": "f706a8e926068a81ade357ef55479af6ee08ccb0",
     "json": "build/module.json",
     "build": [["gcc", "-std=c11", "-O3", "-shared", "-fPIC", "-w", "-fvisibility=hidden", "-fno-math-errno",
                "src/tinypro5.c", "src/presets_factory.c", "src/bank.c", "src/overlay.c", "src/h2p.c",
                "src/bankscan.c", "src/meta.c", "src/plugin.c", "-o", "{out}", "-lm"],
               ["mkdir", "-p", "build"],
               ["gcc", "-std=c11", "-O1", "-w", "-o", "build/gen_module_json", "tools/gen_module_json.c",
                "src/meta.c", "src/tinypro5.c", "src/presets_factory.c", "src/bank.c", "src/overlay.c", "-lm"],
               ["build/gen_module_json", "build/module.json"]]},
    {"id": "je8086", "title": "JE-8086", "kind": "synth", "license": "GPL-3.0 (Gearmulator)",
     "repo": "charlesvestal/schwung-je8086", "commit": "76e96e1eea5cc9192c7d320916a7f9e30cabad2a",
     "json": "src/module.json", "files": ["build/jp8000-dsp", "src/help.json"],
     "one_copy": True,               # it runs the JP-8000's own firmware: too heavy to run twice
     "roms": "je8086",               # its roms/ folder is ~/console-data/roms/je8086 (the file page's ROMS)
     "build": [["git", "submodule", "update", "--init", "--depth", "1", "libs/gearmulator"],
               ["git", "-C", "libs/gearmulator", "submodule", "update", "--init", "--depth", "1",
                "source/cpu/dsp56300", "source/cpu/mc68k"],
               ["git", "-C", "libs/gearmulator/source/cpu/dsp56300", "submodule", "update", "--init", "--depth",
                "1", "source/asmjit"],
               ["{cmake}", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
               ["{cmake}", "--build", "build", "--target", "jp8000-move-plugin", "jp8000-dsp", "-j2"],
               ["cp", "build/dsp.so", "{out}"]]},
    {"id": "amino", "title": "AMINO", "kind": "synth", "license": "MIT",
     "repo": "klaine/amino", "commit": "5c8ce7c9725b5d02471c98d78be182e223428a0d",
     "json": "modules/sound_generators/amino/module.json", "files": ["presets"],
     "build": [["gcc", "-std=c11", "-O2", "-shared", "-fPIC", "-w", "-Isrc/dsp", "src/dsp/*.c", "-o", "{out}",
                "-lm", "-ldl"]]},
    # ---------------------------------------------------------------- ready-made from Schwung's releases
    # (their own Move builds, downloaded when the libraries are built: see build.py "asset")
    {"id": 'model-72', "title": 'MODEL-72', "kind": 'synth', "license": "see its repo",
     "repo": 'sd88me/schwung-model72', "commit": "release", "json": "module.json", "build": [],
     "asset": 'model-72-module.tar.gz'},
    {"id": '303', "title": '303', "kind": 'synth', "license": "see its repo",
     "repo": 'charlesvestal/schwung-303', "commit": "release", "json": "module.json", "build": [],
     "asset": '303-module.tar.gz'},
    {"id": 'noisemaker', "title": 'NOISEMAKER', "kind": 'synth', "license": "see its repo",
     "repo": 'legsmechanical/schwung-noisemaker', "commit": "release", "json": "module.json", "build": [],
     "asset": 'noisemaker-module.tar.gz',
     "quiet_first": ["voices"]},    # VOICES set while notes sound (even to the same value) crashed it: fxprobe.py
    {"id": 'tenebrae', "title": 'TENEBRAE', "kind": 'synth', "license": "see its repo",
     "repo": 'legsmechanical/schwung-tenebrae', "commit": "release", "json": "module.json", "build": [],
     "asset": 'tenebrae-module.tar.gz'},
    {"id": 'nusaw', "title": 'NUSAW', "kind": 'synth', "license": "see its repo",
     "repo": 'charlesvestal/schwung-nusaw', "commit": "release", "json": "module.json", "build": [],
     "asset": 'nusaw-module.tar.gz'},
    {"id": 'omega', "title": 'OMEGA', "kind": 'drums', "license": "see its repo",
     "repo": 'james-fish/schwung-omega', "commit": "release", "json": "module.json", "build": [],
     "asset": 'omega-module.tar.gz'},
    {"id": 'quark', "title": 'QUARK', "kind": 'synth', "license": "see its repo",
     "repo": 'james-fish/schwung-quark', "commit": "release", "json": "module.json", "build": [],
     "asset": 'quark-module.tar.gz'},
    {"id": 'crest', "title": 'CREST', "kind": 'synth', "license": "see its repo",
     "repo": 'klaine/crest', "commit": "release", "json": "module.json", "build": [],
     "asset": 'crest-module.tar.gz'},
    {"id": 'chordism', "title": 'CHORDISM', "kind": 'synth', "license": "see its repo",
     "repo": 'charlesvestal/schwung-chordism', "commit": "release", "json": "module.json", "build": [],
     "asset": 'chordism-module.tar.gz'},
    {"id": 'setbfree-organ', "title": 'SETBFREE TONEWHEEL ORGAN', "kind": 'synth', "license": "see its repo",
     "repo": 'pdubucq/schwung-setbfree', "commit": "release", "json": "module.json", "build": [],
     "asset": 'setbfree-organ-module.tar.gz'},
    {"id": 'sf2', "title": 'SF2 SYNTH', "kind": 'synth', "license": "see its repo",
     "repo": 'charlesvestal/schwung-sf2', "commit": "release", "json": "module.json", "build": [],
     "asset": 'sf2-module.tar.gz'},
    {"id": 'surge', "title": 'SURGE XT', "kind": 'synth', "license": "see its repo",
     "repo": 'charlesvestal/schwung-surge', "commit": "release", "json": "module.json", "build": [],
     "asset": 'surge-module.tar.gz'},
    {"id": 'mono-voice', "title": 'MONO VOICE', "kind": 'synth', "license": "see its repo",
     "repo": 'timncox/schwung-mono', "commit": "release", "json": "module.json", "build": [],
     "asset": 'mono-voice-module.tar.gz'},
    {"id": 'hank', "title": 'HANK', "kind": 'synth', "license": "see its repo",
     "repo": 'charlesvestal/schwung-hank', "commit": "release", "json": "module.json", "build": [],
     "asset": 'hank-module.tar.gz'},
    {"id": 'tablor', "title": 'TABLOR', "kind": 'synth', "license": "see its repo",
     "repo": 'athousanddetails/schwung-tablor', "commit": "release", "json": "module.json", "build": [],
     "asset": 'tablor-module.tar.gz'},
    {"id": 'mrsample', "title": 'MRSAMPLE', "kind": 'synth', "license": "see its repo",
     "sample_key": "sample_path",                 # (its one sample is chosen in the sample browser: push the wheel)
     "repo": 'charlesvestal/schwung-mrsample', "commit": "release", "json": "module.json", "build": [],
     "asset": 'mrsample-module.tar.gz'},
    {"id": 'chiptune', "title": 'CHIPTUNE', "kind": 'synth', "license": "see its repo",
     "repo": 'charlesvestal/schwung-chiptune', "commit": "release", "json": "module.json", "build": [],
     "asset": 'chiptune-module.tar.gz'},
    {"id": 'bizar', "title": 'BIZAR', "kind": 'synth', "license": "see its repo",
     "repo": 'klaine/bizar', "commit": "release", "json": "module.json", "build": [],
     "asset": 'bizar-module.tar.gz'},
]

FX = []                             # the audio effects (from FX_ASSETS below, once downloaded)
FX_ASSETS = [                       # ready-made effects from Schwung's releases (downloaded by build.py), in the picker's order
    {"id": 'filter', "title": 'FILTER', "kind": "fx", "repo": 'charlesvestal/schwung-filter',
     "asset": 'filter-module.tar.gz', "json": "module.json", "build": [], "cat": 'filter'},
    {"id": '4k-eq', "title": '4K EQ', "kind": "fx", "repo": 'athousanddetails/schwung-4keq',
     "asset": '4k-eq-module.tar.gz', "json": "module.json", "build": [], "cat": 'filter'},
    {"id": 'spectra', "title": 'SPECTRA', "kind": "fx", "repo": 'filliformes/spectra-move',
     "asset": 'spectra-module.tar.gz', "json": "module.json", "build": [], "cat": 'filter'},
    {"id": 'ottx', "title": 'OTTX', "kind": "fx", "repo": 'legsmechanical/schwung-ottx',
     "asset": 'ottx-module.tar.gz', "json": "module.json", "build": [], "cat": 'dynamics'},
    {"id": 'busdriver', "title": 'BUS DRIVER', "kind": "fx", "repo": 'legsmechanical/schwung-busdriver',
     "asset": 'busdriver-module.tar.gz', "json": "module.json", "build": [], "cat": 'dynamics'},
    {"id": 'gate', "title": 'GATE', "kind": "fx", "repo": 'charlesvestal/schwung-gate',
     "asset": 'gate-module.tar.gz', "json": "module.json", "build": [], "cat": 'dynamics'},
    {"id": 'pushnpull', "title": 'PUSHNPULL', "kind": "fx", "repo": 'legsmechanical/schwung-pushnpull',
     "asset": 'pushnpull-module.tar.gz', "json": "module.json", "build": [], "cat": 'dynamics'},
    {"id": 'ducker', "title": 'DUCKER', "kind": "fx", "repo": 'charlesvestal/schwung-ducker',
     "asset": 'ducker-module.tar.gz', "json": "module.json", "build": [], "cat": 'dynamics'},
    {"id": 'tapescam', "title": 'TAPESCAM', "kind": "fx", "repo": 'charlesvestal/schwung-tapescam',
     "asset": 'tapescam-module.tar.gz', "json": "module.json", "build": [], "cat": 'drive'},
    {"id": 'chowtape', "title": 'CHOWTAPE', "kind": "fx", "repo": 'charlesvestal/schwung-chowtape',
     "asset": 'chowtape-module.tar.gz', "json": "module.json", "build": [], "cat": 'drive'},
    {"id": 'superboom', "title": 'SUPER BOOM', "kind": "fx", "repo": 'filliformes/super-boom-move',
     "asset": 'super-boom-module.tar.gz', "json": "module.json", "build": [], "cat": 'drive'},
    {"id": 'junologue-chorus', "title": 'JUNOLOGUE CHORUS', "kind": "fx", "repo": 'charlesvestal/schwung-junologue-chorus',
     "asset": 'junologue-chorus-module.tar.gz', "json": "module.json", "build": [], "cat": 'mod'},
    {"id": 'stereoid', "title": 'STEREOID', "kind": "fx", "repo": 'legsmechanical/schwung-stereoid',
     "asset": 'stereoid-module.tar.gz', "json": "module.json", "build": [], "cat": 'util'},
    {"id": 'usefulity', "title": 'USEFULITY', "kind": "fx", "repo": 'charlesvestal/schwung-usefulity',
     "asset": 'usefulity-module.tar.gz', "json": "module.json", "build": [], "cat": 'util'},
    {"id": 'tapedelay', "title": 'TAPEDELAY', "kind": "fx", "repo": 'charlesvestal/schwung-space-delay',
     "asset": 'tapedelay-module.tar.gz', "json": "module.json", "build": [], "cat": 'delay'},
    {"id": 'tape-echo2', "title": 'TAPE ECHO 2', "kind": "fx", "repo": 'athousanddetails/schwung-tape-echo2',
     "asset": 'tape-echo2-module.tar.gz', "json": "module.json", "build": [], "cat": 'delay'},
    {"id": 'ruminant', "title": 'RUMINANT', "kind": "fx", "repo": 'mestela/schwung-ruminant',
     "asset": 'ruminant-module.tar.gz', "json": "module.json", "build": [], "cat": 'delay'},
    {"id": 'munchi-delay', "title": 'MUNCHI DELAY', "kind": "fx", "repo": 'charlesvestal/schwung-munchi-delay',
     "asset": 'munchi-delay-module.tar.gz', "json": "module.json", "build": [], "cat": 'delay'},
    {"id": 'mverb', "title": 'MVERB', "kind": "fx", "repo": 'charlesvestal/schwung-mverb',
     "asset": 'mverb-module.tar.gz', "json": "module.json", "build": [], "cat": 'reverb'},
    {"id": 'dragonfly-hall', "title": 'DRAGONFLY HALL', "kind": "fx", "repo": 'wolfrenegade1976/move-anything-dragonfly-hall',
     "asset": 'dragonfly-hall-module.tar.gz', "json": "module.json", "build": [], "cat": 'reverb'},
    {"id": 'cloudseed', "title": 'CLOUDSEED', "kind": "fx", "repo": 'charlesvestal/schwung-cloudseed',
     "asset": 'cloudseed-module.tar.gz', "json": "module.json", "build": [], "cat": 'reverb'},
    {"id": 'midiverb', "title": 'MIDIVERB', "kind": "fx", "repo": 'charlesvestal/schwung-midiverb',
     "asset": 'midiverb-module.tar.gz', "json": "module.json", "build": [], "cat": 'reverb'},
    {"id": 'psxverb', "title": 'PSX VERB', "kind": "fx", "repo": 'charlesvestal/schwung-psxverb',
     "asset": 'psxverb-module.tar.gz', "json": "module.json", "build": [], "cat": 'reverb'},
    {"id": 'rrverb10', "title": 'RRVERB-10', "kind": "fx", "repo": 'legsmechanical/schwung-rrverb10',
     "asset": 'rrverb10-module.tar.gz', "json": "module.json", "build": [], "cat": 'reverb'},
    {"id": 'shimmerwash', "title": 'SHIMWASH', "kind": "fx", "repo": 'twinpowers/schwung-shimwash',
     "asset": 'shimmerwash-module.tar.gz', "json": "module.json", "build": [], "cat": 'reverb'},
    {"id": 'granular', "title": 'BORIS GRANULAR', "kind": "fx", "repo": 'filliformes/boris-move',
     "asset": 'boris-granular-module.tar.gz', "json": "module.json", "build": [], "cat": 'grain'},
    {"id": 'verglas', "title": 'VERGLAS', "kind": "fx", "repo": 'filliformes/verglas-move',
     "asset": 'verglas-module.tar.gz', "json": "module.json", "build": [], "cat": 'grain'},
    {"id": 'gresil', "title": 'GRESIL', "kind": "fx", "repo": 'filliformes/gresil-move',
     "asset": 'gresil-module.tar.gz', "json": "module.json", "build": [], "cat": 'grain'},
    {"id": 'structor', "title": 'STRUCTOR', "kind": "fx", "repo": 'filliformes/structor-move',
     "asset": 'structor-module.tar.gz', "json": "module.json", "build": [], "cat": 'grain',
     "off": "damages memory and crashes Console (fxprobe.py together)"},
    {"id": 'dissolver', "title": 'DISSOLVER', "kind": "fx", "repo": 'filliformes/dissolver-move',
     "asset": 'dissolver-module.tar.gz', "json": "module.json", "build": [], "cat": 'grain'},
    {"id": 'capicola', "title": 'CAPICOLA', "kind": "fx", "repo": 'charlesvestal/schwung-capicola',
     "asset": 'capicola-module.tar.gz', "json": "module.json", "build": [], "cat": 'grain'},
    {"id": 'palette', "title": 'PALETTE', "kind": "fx", "repo": 'filliformes/palette-move',
     "asset": 'palette-module.tar.gz', "json": "module.json", "build": [], "cat": 'multi'},
    {"id": 'work', "title": 'WORK', "kind": "fx", "repo": 'timncox/schwung-work',
     "asset": 'work-module.tar.gz', "json": "module.json", "build": [], "cat": 'multi'},
    {"id": 'clap', "title": 'AIRWINDOWS', "kind": "fx", "repo": 'charlesvestal/schwung-airwindows',
     "asset": 'clap-module.tar.gz', "json": "module.json", "build": [], "cat": 'multi'},
    {"id": 'war_bells', "title": 'WAR BELLS', "kind": "fx", "repo": 'seajaysec/war-bells',
     "asset": 'war_bells-module.tar.gz', "json": "module.json", "build": [], "cat": 'multi'},
    {"id": 'ambiotica', "title": 'AMBIOTICA', "kind": "fx", "repo": 'charlesvestal/schwung-ambiotica',
     "asset": 'ambiotica-module.tar.gz', "json": "module.json", "build": [], "cat": 'multi'},
]


def add_record(mid, r):
    """One installed module joins the instruments (MODULES) or the effects (FX). Works while the app runs."""
    if mid in {m["id"] for m in MODULES} or mid in {m["id"] for m in FX}:
        return
    if r.get("kind") == "fx":
        FX.append({"id": mid, "title": r["title"], "dsp": r.get("dsp", mid + ".so"), "json": "module.json",
                   "description": r.get("description", "")})
    else:
        MODULES.append({"id": mid, "title": r["title"], "kind": r.get("kind", "synth"), "license": "see its repo",
                        "repo": r.get("repo", ""), "commit": "installed", "json": "module.json", "build": [],
                        "prebuilt": True})
        BY_ID[mid] = MODULES[-1]


def _add_installed():
    """What store.py has installed."""
    try:
        import store
        reg = store.installed()
    except Exception:                                   # noqa: BLE001
        return
    fx_ids = {a["id"] for a in FX_ASSETS}
    for mid, r in reg.items():
        if mid in fx_ids:
            continue                          # (effects come from FX_ASSETS, in the picker's order)
        if os.path.exists(os.path.join(store.MODULES_DIR, mid)):
            add_record(mid, r)


import os  # noqa: E402
BY_ID = {m["id"]: m for m in MODULES}
_add_installed()


def _add_fx_assets():
    here = os.path.dirname(os.path.abspath(__file__))
    for a in FX_ASSETS:
        if a.get("off"):
            continue                          # (taken out: see its "off")
        folder = os.path.join(here, "modules", a["id"])
        try:
            info = json.load(open(os.path.join(folder, "module.json")))
        except (OSError, ValueError):
            continue
        add_record(a["id"], {"kind": "fx", "title": a["title"], "dsp": info.get("dsp") or a["id"] + ".so",
                             "description": info.get("description", "")})


_add_fx_assets()


def recipe_version(m):
    """A short tag of how a module is built, so changing its recipe here builds it again."""
    parts = [m["build"], m["json"], m.get("files", [])] + ([m["patches"]] if m.get("patches") else [])
    return ":" + hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:8]
