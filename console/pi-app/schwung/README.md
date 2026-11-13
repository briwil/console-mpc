# Schwung sound generators

Instruments from the [Schwung](https://github.com/charlesvestal/schwung) catalog (modules for the Ableton
Move), run on the Pi through Console's own small host.

- `plugin_api_v1.h` is Schwung's plugin API (MIT, `LICENSE-SCHWUNG`), unchanged. `host.c` is the host side
  of it, cut down to what Console needs; `modules.py` makes a module into one of Console's instruments.
- `catalog.py` lists each module: its GitHub repository, the exact commit Console uses, and how to compile
  it. `build.py` fetches and builds them into `modules/` on the Pi (the app does this by itself at start,
  in the background). Their code is not kept in this repository.

| Module | Kind | Author | License |
|---|---|---|---|
| Forge | drums | Vincent Fillion (filliformes) | MIT |
| Weird Dreams | drums | filliformes | MIT |
| Libpo32 | drums | mestela (libpo32 / Tonic engine) | none stated |
| CW-78 | drums | A Thousand Details | GPL-3.0 (with additional terms, see its NOTICE) |
| SIMIAN | drums | legsmechanical | GPL-3.0 |
| OB-Xd | synth | charlesvestal (OB-Xd) | GPL-3.0 |
| Dexed | synth | charlesvestal (Dexed / MSFA) | GPL-3.0 |
| Braids | synth | charlesvestal (Mutable Instruments) | MIT |
| Hush One | synth | charlesvestal | MIT |
| RaffoSynth | synth | charlesvestal | MIT |
| Hera | synth | charlesvestal (Hera) | GPL-3.0 |
| Plaits | synth | j3threejay (Mutable Instruments) | MIT |
| Essaim, Denis, Aphex, Fizzik | synth | filliformes | MIT |
| Wurl | synth | filliformes (OpenWurli) | GPL-3.0 |
| Maze Voice | synth | sd88me | MIT |
| Quilt | synth | kliegsablaze | PolyForm Strict 1.0.0 (personal, non-commercial use; no changes) |
| CHONK | synth | legsmechanical | GPL-3.0 |
| TinyK, TinyPro5 | synth | fleshinachair | MIT |
| Amino | synth | klaine | MIT |
| JE-8086 | synth | charlesvestal (Gearmulator) | GPL-3.0; needs your own JP-8000 ROM |

Each module keeps its own license; read it in `src/<id>/` once built. The GPL ones mean that if Console
were ever given to anyone with them in it, Console's code would have to go with it under the GPL too.
