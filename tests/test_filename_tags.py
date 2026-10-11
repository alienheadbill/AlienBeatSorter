import pytest
from beatsorter.filename_tags import parse_filename
from beatsorter.keys import Key

def k(s):
    from beatsorter.keys import parse_key_name
    return parse_key_name(s)

CASES = [
    ("Midnight 140bpm Am.wav", 140, "A minor"),
    ("dark_beat_C#min_92.wav", 92, "C# minor"),
    ("Type Beat (140 BPM, F#m).mp3", 140, "F# minor"),
    ("loop - 128 - Bb.wav", 128, "Bb major"),
    ("Song in A minor.wav", None, "A minor"),
    ("A# minor 150 bpm.wav", 150, "Bb minor"),
    ("ebmaj 100bpm trap.wav", 100, "Eb major"),
    ("140bpmAm.wav", 140, "A minor"),
    ("Amin140.wav", 140, "A minor"),
    ("BPM_95_Key_Dm.wav", 95, "D minor"),
    ("[FREE] Drake Type Beat - Lost (prod. X) 140 BPM C# Minor.mp3", 140, "C# minor"),
    ("Key of G 90.wav", 90, "G major"),
    ("F sharp minor 120bpm.wav", 120, "F# minor"),
    ("92.5bpm Cm.wav", 92.5, "C minor"),
    ("Gm 145.wav", 145, "G minor"),
    ("vibe_Cmaj7_110bpm.wav", 110, "C major"),
    # Bill's naming style
    ("1st_Chain__127_fm_.wav", 127, "F minor"),
    ("Complicated_84_gm.wav", 84, "G minor"),
    ("Drive_thru_5th_ward__152___cmin_.wav", 152, "C minor"),
    ("Speeding_in_the_64_150_Em.wav", 150, "E minor"),
    ("Treetop_144.wav", 144, None),
    ("So_much_on_my_chest_160_A.wav", 160, "A major"),
    ("Serenity_163bpm_Cmajor_Prod_TLibs_x_bailey.mp3", 163, "C major"),
    ("Stickky_194bpm_Dm.mp3", 194, "D minor"),
    # false-positive guards
    ("i am here.wav", None, None),
    ("Beat 120 am.wav", 120, "A minor"),
    ("808 Boom.wav", None, None),
    ("Kick v2.wav", None, None),
    ("beat 3.wav", None, None),
    ("Summer 2024 mix.wav", None, None),
    ("Who I Am.wav", None, None),
    ("Let Em Know.wav", None, None),
    ("Dark Ambient Pad.wav", None, None),
    ("3 AM vibes 140bpm.wav", 140, None),
    ("not a major thing.wav", None, None),
    ("Part A 2.wav", None, None),
    ("140bpm 150bpm.wav", None, None),
    ("Am Cm 140.wav", 140, None),  # two keys conflict -> unsure
    ("Beat 120.wav", 120, None),  # trailing number = BPM (your naming style)
]

@pytest.mark.parametrize("name,bpm,key", CASES)
def test_parse(name, bpm, key):
    t = parse_filename(name)
    assert t.bpm == bpm, (name, t)
    assert (t.key.name if t.key else None) == key, (name, t)


def test_camelot_wheel():
    from beatsorter.keys import camelot, compatible, parse_key_name
    k = parse_key_name
    assert camelot(k("F minor")) == "4A" and camelot(k("C major")) == "8B"
    assert camelot(k("Ab minor")) == "1A" and camelot(k("E major")) == "12B"
    assert {x.short for x in compatible(k("F minor"))} == {"Fm", "Ab", "Cm", "Bbm"}
    assert {x.short for x in compatible(k("C# minor"))} == {"C#m", "E", "Abm", "F#m"}  # wraps 12A->1A
    # every key maps to a unique code
    from beatsorter.keys import Key
    codes = {camelot(Key(pc, m)) for pc in range(12) for m in ("minor", "major")}
    assert len(codes) == 24


def test_oneshot_names():
    from beatsorter.oneshots import type_from_name
    cases = {
        "Kick 01.wav": "Kicks", "Hard_Kik_3.wav": "Kicks", "BD_punchy.wav": "Kicks",
        "808 Kick Boom.wav": "Kicks", "Kick 808 hard.wav": "Kicks",  # an 808 kick is a kick
        "Packs/808s/Zay 808 C.wav": "808s", "sub bass long.wav": "808s",
        "Open Hat 2.wav": "Hi-Hats", "HH_closed_04.wav": "Hi-Hats", "hihat roll.wav": "Hi-Hats",
        "Snare - Crack.wav": "Snares", "Rimshot dry.wav": "Snares", "Clap Big.wav": "Claps",
        "snap 3.wav": "Claps", "Crash 1.wav": "Cymbals", "Shaker loop.wav": "Percussion",
        "Riser FX 2.wav": "FX", "Vox Chop Hey.wav": "Vox", "Drums/Kicks/sound 12.wav": "Kicks",
        "Hats/x1.wav": "Hi-Hats", "Chopped Soul.wav": None, "Bdayy.wav": None,
        "Phat Lead.wav": "Melodic", "Chase.wav": None,
    }
    wrong = {n: type_from_name(n) for n, e in cases.items() if type_from_name(n) != e}
    assert not wrong, wrong
