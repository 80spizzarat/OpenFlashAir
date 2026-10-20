param([string]$ReleaseLabel = '0.1.0', [string]$Python = 'python', [Parameter(Mandatory=$true)][string]$PystraySource)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $project (Join-Path 'dist' "OpenFlashAir-$ReleaseLabel")
$workRoot = Join-Path $project (Join-Path 'work' "pyinstaller-$ReleaseLabel")
$specRoot = Join-Path $project (Join-Path 'work' "pyinstaller-spec-$ReleaseLabel")
& $Python -m PyInstaller --noconfirm --clean --windowed --name OpenFlashAir `
  --exclude-module numpy `
  --exclude-module pystray `
  --hidden-import six.moves `
  --add-data ("{0};pystray" -f $PystraySource) `
  --icon (Join-Path $project 'openflashair\OpenFlashAir_icon_centered.ico') `
  --add-data ("{0};openflashair" -f (Join-Path $project 'openflashair\OpenFlashAir_icon_centered.ico')) `
  --add-data ("{0};openflashair\assets" -f (Join-Path $project 'openflashair\assets')) `
  --paths $project --distpath $distRoot --workpath $workRoot `
  --specpath $specRoot (Join-Path $project 'run_openflashair.py')
