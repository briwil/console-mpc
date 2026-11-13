"""A brand-new project starts with every instrument slot empty.

Console's Engine.load() treats a project that has no project.json yet (a fresh card: the first start) like an old song from
before there were instrument slots, and puts the drum machine (the LXR-02) in slot 1. A song that has been saved always has
project.json (with its own "slots"), so this only changes the very first start: after loading, a project that had no
project.json gets empty slots, like every other new project (Engine._reset does the same)."""
import os


def install(audio_mod):
    E = audio_mod.Engine
    orig = E.load

    def load(self):
        fresh = not os.path.exists(os.path.join(self.project_dir, "project.json"))
        r = orig(self)
        if fresh:
            with self.lock:
                self.slots = [None] * len(self.slots)
                self.slot = None
                self.slot_mutes = set()
        return r
    E.load = load
