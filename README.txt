BEAT SORTER
===========
Sorts your beats, loops and one-shots into BPM and key folders for the
FL Studio Browser. Your original files are only READ: nothing in your
beats folder is ever moved, renamed or changed.


SETUP (once)
------------
1. If you don't have Python: install Python 3.12 from
   https://www.python.org/downloads/windows/
   and tick "Add python.exe to PATH" on the first install screen.
2. Unzip this folder somewhere permanent (e.g. Documents\BeatSorter).
3. Double-click setup.bat. It installs the audio libraries (a few minutes).
4. Optional: double-click "Create desktop shortcut.bat" for a desktop
   shortcut with the alien-head icon.


USING IT
--------
1. Double-click "Beat Sorter.bat".
2. "Your beats": pick the folder with your beats.
   "Sorted folder": pick a NEW empty folder. Put it on the SAME DRIVE as
   your beats (e.g. D:\Beats -> D:\Beats Sorted) so no extra space is used.
3. Click "1. Analyze". The first run takes a while (about 3 seconds
   per beat, split across your CPU cores). Results are saved, so later runs
   only analyze new or changed files. You can Cancel and continue later.
4. Look at the results. Click "Accuracy report" to see how detection
   compares with the BPM/key already in your file names.
5. Click "2. Build Sorted Folder".
6. In FL Studio: Options > File settings > Browser extra search folders,
   add the Sorted folder. Refresh the Browser after each rebuild.


HOW FILES ARE SORTED
--------------------
  140-149 BPM\C minor\       BPM range (10 BPM per folder) + key
  140-149 BPM\No Key\        drum loops (tempo, no key)
  No BPM\A minor\            pads/textures with no steady beat
  One-Shots\Kicks\, 808s\...  short sounds, by type (Kicks, 808s, Snares, Hi-Hats...)
  _Review\140-149 BPM\...\   detection wasn't sure: best guess, check by ear
  140-149 BPM\Key unknown\   no key in the name, and "Use detected key" is off
  Tags\dark\, Tags\drill\    one folder per tag you create (see below)
Folders are zero-padded ("080-089 BPM") so FL lists them in order.
Links inside Sorted are named with their BPM/key, e.g. "Nasty [142 Cm]",
so typing 142 or Cm in FL Studio's Browser search finds them instantly.

If a file name already has the BPM or key (e.g. "Midnight 140bpm Am"),
the name wins over detection. If detection strongly disagrees, the file
is still sorted by its name but marked in the "Notes" column; use the
"Name vs. detection differ" filter to find those.


ABOUT THE SORTED FOLDER
-----------------------
* Files in Sorted are hard links: a second name for the same file, using
  no extra space. Deleting or renaming something in Sorted does NOT
  affect your original.
* One catch: if you EDIT a file's audio in place (for example a
  destructive save in Edison), that edits the original too, because both
  names point to the same audio. Normal use in FL (dragging into
  playlists/channels) never modifies the file.
* If Sorted is on a different drive, or a drive that doesn't support
  hard links (exFAT/FAT32 USB drives), Beat Sorter asks before COPYING.
* Rebuilding replaces only what Beat Sorter put there before. Other files
  you add to Sorted are left alone. You can delete the whole Sorted
  folder at any time.


SETTINGS
--------
BPM range: detection can't always tell 70 from 140. Results are halved
  or doubled to land in this range. After each scan, Beat Sorter picks the
  range that best matches the BPMs in your file names (needs at least 5
  named beats; untick "Learn this range" to set it yourself).
One-shots under: shorter files go to One-Shots without BPM/key folders.
Min confidence: below these, a detected BPM/key goes to _Review.
Use detected key for files without a key in the name: on by default.
  Turn it off to keep guessed keys out of your key folders.
Add BPM/key to file names inside Sorted: names the links like
  "Late Night [135 Gm].wav". Originals keep their names.


ACCURACY (be realistic)
-----------------------
Key: three detectors vote: a neural network trained on thousands of
  tracks (from the madmom research library) and two Essentia-style key
  finders (the method behind many online key sites), one tuned for
  electronic music. On 17 of your beats, with Tunebat's answer used where
  it differed from the file name, the vote was right on 15 (88%). The old
  detector got 10. Of the two misses, one is a beat named Fm where all
  three hear F#m (not yet checked on Tunebat); the other is Em heard as Am.
  Three of those beats were named a half-step off (Cm/Dm where Tunebat
  and all three detectors say C#m/D#m). When all three detectors agree
  against a name, Notes says "name may be off"; right-click > Use detected
  key if your ears agree. Files are still sorted by their name otherwise.
BPM: with the range learned from your names, 16 of 18 beats matched
  exactly (89%). Misses: one beat named 84 detected as 168 (half/double),
  one named 194 detected as 129 (a 2/3 "triplet" error).
These numbers come from a small set of your own beats, so expect some
  variation on others.

BROWSING, TAGS AND PREVIEW (Library tab)
----------------------------------------
* Filters on the left: search, BPM range (e.g. 140 to 150), key buttons,
  and your tags. Click a key or tag button to filter; click again to clear.
  Several tags = beats that have all of them.
* Play: double-click a beat, press Space, or use the Play button.
* Tag: select one or more beats (Ctrl/Shift-click) and click "+ Tag", or
  right-click. Tags are saved by Beat Sorter and never change your files.
  Once the Sorted folder is built, tagging/untagging updates
  Sorted\Tags\<tag>\ right away, so tags work in FL's Browser too.
* Drag into FL Studio: drag beats from the list onto FL's playlist or
  channel rack.


FL STUDIO BROWSER TAGS
----------------------
More > Sync tags to FL Studio puts your tags, BPM ranges (140-149bpm),
keys (Fm) and one-shot types (Kicks) into FL's own Browser tags, so you can
filter by them inside FL (Browser > Tags). Close FL Studio before syncing.
* Tags you made in FL are kept; Beat Sorter only removes tags it added.
* FL's tag file is backed up first. More > Undo last FL sync restores it.
* After you rebuild the Sorted folder, FL's tags are updated automatically.


FIXING, DUPLICATES, COMPATIBLE KEYS
-----------------------------------
* Fix BPM / key: select beats, click Fix (or right-click). Use 1/2x or 2x
  for half-time mix-ups. Your fixes win over file names and detection.
* Compatible keys: click a key in the sidebar, then "+ compatible keys" to
  also see keys that mix well with it (Camelot wheel).
* More > Find duplicates: finds identical files and the same beat saved
  twice (e.g. WAV and MP3). Nothing is deleted; you can tag the extras.


DOWNLOAD FROM YOUTUBE
---------------------
1. Pick your beats folder (and Sorted folder) at the top.
2. Open the "Download from YouTube" tab, paste one or more links (one per
   line), and click "Beam it down". Playlist links ask before downloading.
3. Each beat is saved as WAV or MP3 (switch under the link box) in
   <your beats>\YouTube Downloads, named after
   the video title. BPM/key are read from the title or description
   ("140 BPM | C#m"); if missing, they're detected from the audio.
   The file is then linked straight into your Sorted folder.
* BPM/key only go into the file name when they came from the title or
  description. Detected guesses are used for sorting but not written into
  names, because a name tag is treated as the truth on later scans.
* WAV keeps the full quality of the video's audio and works in every DAW
  (about 30 MB per beat). MP3 is saved at 320 kbps (about 6 MB per beat).
* Videos you've already downloaded are skipped.
* If downloads start failing, click "Update downloader". YouTube changes
  often and the downloader needs to keep up.
* Use this for your own uploads or beats whose producers allow downloads.
  YouTube's terms generally don't allow downloading, and most "free" type
  beats are free for non-profit use only.


UPDATES
-------
Beat Sorter checks for a new version each time it opens. When there is one,
a banner offers "Install & restart": it downloads the new version, keeps a
backup of the current one, installs any new packages, and reopens itself.
Your beats, Sorted folder, tags and settings are never touched.
* More > Check for updates: check right now.
* More > Undo last update: go back to the previous version.
* If an update fails, the previous version is restored automatically.


IF SOMETHING GOES WRONG
-----------------------
Run "Beat Sorter (with console).bat" to see error messages, or look in
%LOCALAPPDATA%\BeatSorter\error.log.
Cached results are in %LOCALAPPDATA%\BeatSorter\cache.db (delete it to
force a full re-analysis).


CREDITS
-------
Key network: Korzeniowski & Widmer, "Genre-Agnostic Key Classification
with Convolutional Neural Networks" (ISMIR 2018), trained weights from the
madmom library, license CC BY-NC-SA 4.0 (non-commercial use only).
Key profiles and method after Essentia (Music Technology Group, UPF) and
Faraldo et al. ("edma" profile).
