set dst=_deploy
rd /s /q %dst%
md %dst%

set src=hoard
set dst=%dst%\hoard
md %dst%

copy LICENSE   %dst%
copy README.md %dst%

copy %src%\config.json.example       %dst%
copy %src%\config.py                 %dst%
copy %src%\filesystem.py             %dst%
copy %src%\gallery.html              %dst%
copy %src%\handle_directory.py       %dst%
copy %src%\handle_file.py            %dst%
copy %src%\handle_request.py         %dst%
copy %src%\handle_thumbnail.py       %dst%
copy %src%\log.py                    %dst%
copy %src%\main.py                   %dst%
copy %src%\plugins.py                %dst%
copy %src%\resources.py              %dst%
copy %src%\requirements.txt          %dst%
copy %src%\stats.py                  %dst%
copy %src%\start.bat                 %dst%

set src=%src%\resources
set dst=%dst%\resources
md %dst%
copy %src%\DejaVuSansMono.ttf        %dst%
copy %src%\Enso.png                  %dst%
copy %src%\Enso.png_LICENSE          %dst%
copy %src%\favicon.svg               %dst%
copy %src%\gallery.js                %dst%
copy %src%\hoard3.png                %dst%
copy %src%\style.css                 %dst%
copy %src%\thumbnail-placeholder.png %dst%
copy %src%\thumbs.js                 %dst%
copy %src%\viewer-mask.png           %dst%

:: render plugins (drop-in .py files)
md _deploy\hoard\plugins
copy hoard\plugins\*.py              _deploy\hoard\plugins

set dst=_deploy
explorer %dst%

:: todo: make a separate build for Windows,
:: run venv and pip install -r on it
:: then zip the result automatically