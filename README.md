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
* Set it to a long random value (e.g. a UUID) to require that callers present a
  `auth=<token>` cookie; everyone else gets a plain *404*. Cookies are per-origin,
  so set it on the main port **and** each `thumbnailPorts` entry.
* The example placeholder (`change-me-to-a-random-uuid`) denies *all* requests —
  the server refuses to run open with the default still in place.

## Optional features (config.json)

* `allowDelete` — enables soft-delete (the *Delete* key renames a file to
  `*.deleted`, hiding it from listings).
* `allowRename` — enables in-place rename of the highlighted file with *F2*.
* `thumbnailPorts` — extra ports the browser round-robins thumbnail requests
  across, to beat the per-origin connection limit.

## Plugins

Drop a `.py` file in `hoard/plugins/` to teach hoard a new file type without
touching the core. See `hoard/plugins/HELP.md` for the plugin contract and a
worked example.
