# hoard Media Server

\* It's actually not so terrible now \*

# Bare Bones but FAST Media Server for Private Networks

<img width="1213" height="897" alt="image" src="https://github.com/user-attachments/assets/221189f1-331d-4bf2-aff7-739522452b14" />

* Install Python 3.11 or newer.
* Make sure to install it to your system's %PATH% variable
* Rename *config.json.example* to *config.json*
* Edit *config.json* to suit your needs

You *ABSOLUTELY MUST* point `roots` at the directories you want to serve. Each
entry becomes a top-level folder in the gallery:

    "roots": [
        { "name": "Photos", "path": "N:\\Pictures" },
        { "name": "Video",  "path": "D:\\Movies" }
    ],

Install dependencies:

    python -m pip install -r requirements.txt

To start the server (from inside `hoard/`):

    python main.py

On Windows you can instead just run `hoard/start.bat`, which creates a virtual
environment, installs dependencies, and launches the server for you.

* Optionally, for camera RAW file support, download *dcraw.exe* (https://github.com/ncruces/dcraw/releases or https://www.dechifro.org/dcraw/). All RAW formats dcraw can decode are supported (Canon, Nikon, Sony, Fujifilm, Olympus, Panasonic, Pentax, Adobe DNG, and more).

## Access control

`authToken` in *config.json* gates every request via an `auth` cookie:

* Leave it `""` (blank) to disable the gate and serve everyone — fine on a
  trusted private network.
* Set it to a long random value (e.g. a UUID) to require that callers present an
  `auth=<token>` cookie; everyone else gets a plain *404*.
* The example placeholder (`change-me-to-a-random-uuid`) denies *all* requests —
  the server refuses to run open with the default still in place.

To log in, just visit `http://<host>:<port>/?auth=<token>` once. The server
stores the cookie (host-wide, so it covers every `thumbnailPorts` entry too) and
redirects to the clean URL. Share that link to grant access.

## Viewer controls

Click a thumbnail (or press *Enter*) to open the viewer; *Escape*/*Enter*
closes it.

* **Arrow keys / scroll** — move between files in the grid and the viewer.
* **Video** — while a video is open, *←*/*→* seek back/forward 5 seconds and
  *Space* toggles play/pause. *f* toggles fullscreen.
* **p** — cycle the file's flag none → pick → reject → none.
* **h** — toggle favorite (independent of the flag).
* **[** / **]** — rotate the file left/right.
* **e** — "open with" menu: pick *File Explorer* (the default) or one of the
  editors configured in `editors`. With no editors configured it just reveals
  the file in your file manager.
* **F2** — rename the file (requires `allowRename`).
* **Delete** — soft-delete the file (requires `allowDelete`).

## Optional features (config.json)

* `allowDelete` — enables soft-delete (the *Delete* key renames a file to
  `*.deleted`, hiding it from listings).
* `allowRename` — enables in-place rename of the highlighted file with *F2*.
* `thumbnailPorts` — extra ports the browser round-robins thumbnail requests
  across, to beat the per-origin connection limit.
* **Adaptive quality on slow links** — if sending a response to a client is too
  slow (a big-enough transfer below `slowClientMinBytesPerSec`, default 1 MB/s),
  hoard assumes that client is on a slow connection and, for the next
  `slowClientHours` (default 2), serves all of its images and thumbnails as
  low-quality JPEGs (`slowClientJpegQuality`, default 50, transparency
  flattened). The terminal status display lists the active clients and flags the
  slow ones with a countdown. Set `slowClientMinBytesPerSec` to `0` to disable.
* `editors` — a list of `{ name, path }` entries, like `roots` (e.g.
  `[{ "name": "Paint", "path": "C:\\Windows\\System32\\mspaint.exe" }]`).
  Pressing *e* on a file pops up an "open with" menu listing *File Explorer*
  first, then each editor by its `name`. Leave it `[]` to make *e* simply reveal
  the file in your file manager.

## Plugins

Drop a `.py` file in `hoard/plugins/` to teach hoard a new file type without
touching the core. See `hoard/plugins/HELP.md` for the plugin contract and a
worked example.
