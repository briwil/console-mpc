# Third-party notices

Console is released under the GNU General Public License v3.0 (see [LICENSE](LICENSE)). It bundles the third-party work below, each under its own licence. Licence texts sit next to the code (`LICENSE*` files) where the authors supplied them.

## Trademarks and hardware

- "Erica Synths", "LXR" and "LXR-02" are trademarks of Erica Synths. Console is not affiliated with or approved by Erica Synths. Truthful compatibility statements are fine; official branding is not allowed. The LXR hardware design is not licensed to anyone and is not part of this repository.
- Ableton and Move are trademarks of Ableton AG. Console is not affiliated with Ableton.

## Drum engines and effects

| Component | Location | Licence |
|---|---|---|
| LXR-02 firmware (Erica Synths), used as a drum engine and modified | `pi-app/drums/lxr/` | GPL-3.0 with extra terms; see `pi-app/drums/lxr/NOTICE.md` (trademarks; modified versions must be marked as modified) |
| Open-XY drums | `pi-app/drums/md/` | MIT |
| OP-XY MNMD drums | `pi-app/drums/md/` | MIT |
| 606 drum engine | `pi-app/drums/schwung/606/` | GPL-3.0 and MIT |
| 808 drum engine | `pi-app/drums/schwung/808/` | GPL-3.0 |
| Reverb ported from Mutable Instruments Elements/Rings (Emilie Gillet) | `pi-app/fx/` | MIT |
| Schwung host (Charles Vestal) | `pi-app/schwung/` | MIT (`LICENSE-SCHWUNG`) |

## Schwung modules (`pi-app/schwung/modules/`)

| Module | Author | Licence | Source of the licence info |
|---|---|---|---|
| 303 | Robin Schmidt / midilab / davemollen / Charles Vestal | GPL-3.0 | module.json |
| 4k-eq | 4K EQ 2 by Dusk Audio (GPL-3.0); port: athousanddetails | GPL-3.0 | LICENSE file |
| ambiotica | Charles Vestal | MIT | module.json |
| amino | AI & Klaine | MIT | Schwung catalog (not yet verified upstream) |
| aphex | Filliformes | MIT | module.json |
| bizar | AI & Klaine | MIT | LICENSE file |
| braids | Emilie Gillet (port: charlesvestal) | MIT | module.json |
| busdriver | legsmechanical | MIT | module.json |
| capicola | Heavylight Industries (port: charlesvestal) | AGPL-3.0 | module.json |
| chiptune | charlesvestal | MIT/LGPL-2.1 | module.json |
| chonk | legsmechanical (DSP: Punk Labs LLC) | GPL-3.0-or-later | module.json |
| chordism | charlesvestal | MIT | module.json |
| chowtape | charlesvestal | GPL-3.0 | module.json |
| clap | charlesvestal, Chris Johnson (Airwindows) | MIT | module.json |
| cloudseed | Ghost Note Audio (port: charlesvestal) | MIT | module.json |
| crest | AI & Klaine | MIT | LICENSE file |
| cw78 | A Thousand Details; every voice modelled from the Roland CR-78 service notes (June 1979), VG-11A voicing board | GPL-3.0 | Schwung catalog (not yet verified upstream) |
| denis | Vincent Fillion | MIT | Schwung catalog (not yet verified upstream) |
| dexed | Dexed/MSFA by google/asb2m10 (port: charlesvestal) | GPL-3.0 | module.json |
| dissolver | fillioning | UNKNOWN | - |
| dragonfly-hall | bradcoomber | GPL-3.0 | module.json |
| ducker | charlesvestal | MIT | module.json |
| essaim | fillioning | MIT | Schwung catalog (not yet verified upstream) |
| filter | charlesvestal | MIT | module.json |
| fizzik | Filliformes | MIT | Schwung catalog (not yet verified upstream) |
| forge | Vincent Fillion | MIT | module.json |
| gate | charlesvestal | MIT | module.json |
| granular | Boris (port: charlesvestal) | GPL-3.0 | module.json |
| gresil | Emilie Gillet (DSP) / filliformes (port) | MIT | module.json |
| hank | charlesvestal | MIT | module.json |
| hera | jpcima (port: charlesvestal) | GPL-3.0 | module.json |
| hush1 | Move Everything Community | MIT | Schwung catalog (not yet verified upstream) |
| je8086 | dsp56300/gearmulator (port: charlesvestal) | GPL-3.0 (Gearmulator) | Schwung catalog (not yet verified upstream) |
| junologue-chorus | Peter Allwin (port: charlesvestal) | MIT | module.json |
| libpo32 | mestela | UNKNOWN | - |
| maze | sd88me | MIT | Schwung catalog (not yet verified upstream) |
| midiverb | Charles Vestal (DSP: thement/midiverb_emulator) | GPL-3.0 | module.json |
| model-72 | sd88me | GPL-3.0 | LICENSE file |
| mono-voice | timncox | UNKNOWN | - |
| mrsample | charlesvestal | MIT | module.json |
| munchi-delay | CHOMPI Club / Chase Bliss (CHOMPI TEMPO, MIT) · port: charlesvestal | MIT | module.json |
| mverb | Andre Louis (DSP: Martin Eastwood) | GPL-3.0 | module.json |
| noisemaker | legsmechanical (engine: Patrick Kunz / TAL) | GPL-2.0 | module.json |
| nusaw | charlesvestal | MIT | module.json |
| obxd | reales (port: charlesvestal) | GPL-3.0 | module.json |
| omega | James Fish | UNKNOWN | - |
| ottx | Schwung OTTx port; DSP by Matt Tytel (Vital), Yegor Suslin (vitOTT) | GPL-3.0 | LICENSE file |
| palette | Filliformes | UNKNOWN | - |
| plaits | Emilie Gillet (port: Justin Joe) | MIT | module.json |
| psxverb | charlesvestal | MIT | module.json |
| pushnpull | legsmechanical | MIT | module.json |
| quark | James Fish & Claude | MIT | LICENSE file |
| quilt | ? | PolyForm Strict 1.0.0 | Schwung catalog (not yet verified upstream) |
| raffo | Nicolas Roulet, Julian Palladino (port: charlesvestal) | MIT | module.json |
| rrverb10 | Schwung RRVerb-10 port; chip emulation by Sergey V. Mikayev (MUNT), ROM research by giulioz | LGPL-2.1-or-later | module.json |
| ruminant | mestela | MIT | LICENSE file |
| setbfree-organ | Robin Gareus, Fredrik Kilander (port: Pascal Dubucq) | UNKNOWN | - |
| sf2 | FluidLite by Robin Lobel (port: charlesvestal) | LGPL-2.1 | module.json |
| shimmerwash | Dan | MIT | LICENSE file |
| simian | legsmechanical | GPL-3.0-or-later | module.json |
| spectra | fillioning | UNKNOWN | - |
| stereoid | legsmechanical | MIT | module.json |
| structor | fillioning | UNKNOWN | - |
| superboom | fillioning | UNKNOWN | - |
| surge | Surge Synth Team (port: charlesvestal) | GPL-3.0 | module.json |
| tablor | athousanddetails; after Wavetable (Roland Rabien / FigBug, BSD-3) | UNKNOWN | - |
| tape-echo2 | Tape Echo 2 by Dusk Audio (GPL-3.0); port: athousanddetails | GPL-3.0 | LICENSE file |
| tapedelay | cyrusasfa (port: charlesvestal) | MIT | module.json |
| tapescam | charlesvestal | MIT | module.json |
| tenebrae | legsmechanical | MIT | module.json |
| tinyk | Mathew Taylor | MIT | module.json |
| tinypro5 | TinyPro5 | MIT | Schwung catalog (not yet verified upstream) |
| usefulity | charlesvestal | MIT | module.json |
| verglas | Emilie Gillet (DSP) / filliformes (port) | UNKNOWN | - |
| war_bells | seajay | AGPL-3.0-or-later | module.json |
| weirddreams | Vincent Fillion (DSP: Daniele Filaretti, MIT) | MIT | module.json |
| work | timncox | UNKNOWN | - |
| wurl | fillioning (port of OpenWurli by hal0zer0) | GPL-3.0 | Schwung catalog (not yet verified upstream) |

## Needs checking before release

- **Remove from the public repo (not redistributable):** quilt. Quilt is PolyForm Strict, which forbids redistribution and modification.
- **Licence unknown, no licence file anywhere:** dissolver, libpo32, mono-voice, omega, palette, setbfree-organ, spectra, structor, superboom, tablor, verglas, work. Ask the author or remove.
- **Licence taken from Schwung's catalog only; confirm in each upstream repo:** amino, cw78, denis, essaim, fizzik, hush1, je8086, maze, tinypro5, wurl.
- Also: `noisemaker` is GPL-2.0, `capicola` and `war_bells` are AGPL-3.0 (network-use clause), and `chiptune` is dual MIT/LGPL-2.1.
