param(
    [Parameter(Position = 0)]
    [string]$Source,
    [int[]]$Slots,
    [int]$Height = -1,
    [double]$ObjectScale = 0.8,
    [switch]$RoomLab,
    [string]$DesignRoom
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path "$Root\.venv\Scripts\python.exe")) {
    py -3 -m venv "$Root\.venv"
    & "$Root\.venv\Scripts\python.exe" -m pip install -r "$Root\requirements.txt"
}

if ($RoomLab) {
    if ($Source -or $Slots -or $Height -ge 0 -or $PSBoundParameters.ContainsKey("ObjectScale")) {
        throw "-RoomLab cannot be combined with asset build parameters"
    }
    & "$Root\.venv\Scripts\python.exe" "$Root\scripts\build_room_assets.py" --root $Root
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & "$Root\.venv\Scripts\python.exe" "$Root\scripts\build_room_lab.py" --root $Root
    exit $LASTEXITCODE
}

if ($DesignRoom) {
    if ($Source -or $Slots -or $Height -ge 0 -or $PSBoundParameters.ContainsKey("ObjectScale") -or $RoomLab) {
        throw "-DesignRoom cannot be combined with asset build parameters"
    }
    & "$Root\.venv\Scripts\python.exe" "$Root\scripts\build_room_proposal.py" --root $Root --room $DesignRoom
    exit $LASTEXITCODE
}

if ($Source) {
    $BuildArgs = @("$Root\scripts\build_asset.py", $Source, "--root", $Root)
    if ($Slots) {
        if ($Slots.Count -ne 3) {
            throw "-Slots requires exactly three values: X,Y,Z"
        }
        $BuildArgs += "--slots"
        $BuildArgs += $Slots
        $BuildArgs += @("--object-scale", $ObjectScale)
    }
    if ($Height -ge 0) {
        if ($Slots) {
            throw "-Height applies only to terrain; object height is declared by slot Z"
        }
        $BuildArgs += @("--height", $Height)
    }
    & "$Root\.venv\Scripts\python.exe" @BuildArgs
    exit $LASTEXITCODE
}

if ($Slots -or $Height -ge 0 -or $PSBoundParameters.ContainsKey("ObjectScale")) {
    throw "Provide a source image when using -Slots, -Height, or -ObjectScale"
}

& "$Root\.venv\Scripts\python.exe" "$Root\scripts\build_all.py" --root $Root
exit $LASTEXITCODE
