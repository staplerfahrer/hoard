# hoard Media Server

\* It's actually not so terrible now \*

# Bare Bones but FAST Media Server for Private Networks

<img width="1213" height="897" alt="image" src="https://github.com/user-attachments/assets/221189f1-331d-4bf2-aff7-739522452b14" />

* Install Python 3.11 or newer.
* Make sure to install it to your system's %PATH% variable
* Rename *config.json.example* to *config.json*
* Edit *config.json* to suit your needs

You *ABSOLUTELY MUST* modify the line to point to your pictures directory:

    "root": "N:\\Pictures",

Install dependencies:

    python -m pip install -r requirements.txt

To start the server:

    python main.py

* Optionally, for camera RAW file support, download *dcraw.exe* (https://github.com/ncruces/dcraw/releases or https://www.dechifro.org/dcraw/). All RAW formats dcraw can decode are supported (Canon, Nikon, Sony, Fujifilm, Olympus, Panasonic, Pentax, Adobe DNG, and more).
