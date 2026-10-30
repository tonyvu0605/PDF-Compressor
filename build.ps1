#Requires -Version 5.1
<#
Builds PDF Compressor: the PyInstaller one-folder app, then the Inno Setup
installer, then the portable zip. Run it from any folder:
    powershell -ExecutionPolicy Bypass -File .\build.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    # PyInstaller logs to stderr. When the caller redirects this script's
    # output, Windows PowerShell 5.1 turns each stderr line into an error
    # record, which "Stop" would treat as fatal, so judge by the exit code.
    $ErrorActionPreference = "Continue"
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe failed with exit code $LASTEXITCODE."
    }
}

function Find-Iscc {
    $folders = @(
        (Join-Path $env:ProgramFiles "Inno Setup 7"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7 (32-bit)"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6")
    )
    foreach ($folder in $folders) {
        $iscc = Join-Path $folder "ISCC.exe"
        if (Test-Path -LiteralPath $iscc) {
            return $iscc
        }
    }
    return $null
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "The virtual environment is missing. Run: python -m venv .venv, then .venv\Scripts\pip install -e "".[dev]"""
    }
    $iscc = Find-Iscc
    if (-not $iscc) {
        throw "Inno Setup is missing. Install it with: winget install -e --id JRSoftware.InnoSetup.7 --scope user"
    }

    # Single quotes only inside: PowerShell 5.1 strips double quotes from
    # arguments it passes to native programs.
    $readVersion = "import sys, tomllib; print(tomllib.load(open(sys.argv[1], 'rb'))['project']['version'])"
    $version = & $python -I -c $readVersion (Join-Path $PSScriptRoot "pyproject.toml")
    if ($LASTEXITCODE -ne 0 -or -not $version) {
        throw "Could not read the version from pyproject.toml."
    }
    Write-Host "Building PDF Compressor $version"

    # No hidden imports are needed. Excluding QtNetwork keeps OpenSSL DLLs
    # from Git's PATH entry out of the build.
    Invoke-Native $python @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "PDF Compressor",
        "--specpath", "build", "--workpath", "build", "--distpath", "dist",
        "--exclude-module", "PySide6.QtNetwork",
        "pdf_compressor\__main__.py"
    )
    $app = Join-Path $PSScriptRoot "dist\PDF Compressor"

    # PyMuPDF is AGPL and PySide6 is LGPL: ship their license texts.
    $sitePackages = Join-Path $PSScriptRoot ".venv\Lib\site-packages"
    $licenses = Join-Path $app "licenses"
    foreach ($pattern in @("pymupdf-*.dist-info", "pyside6_essentials-*.dist-info", "shiboken6-*.dist-info")) {
        $info = Get-ChildItem -LiteralPath $sitePackages -Directory -Filter $pattern | Select-Object -First 1
        if (-not $info) {
            throw "Could not find $pattern in the virtual environment."
        }
        $target = Join-Path $licenses ($info.Name -replace "-[^-]+\.dist-info$", "")
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        # METADATA states each package's license choice; the PySide6 wheels
        # ship no license text of their own beyond a commercial notice.
        Get-ChildItem -LiteralPath $info.FullName -File |
            Where-Object { $_.Name -match "^(COPYING|LICENSE|NOTICE|METADATA$)" } |
            Copy-Item -Destination $target
        $packageLicenses = Join-Path $info.FullName "licenses"
        if (Test-Path -LiteralPath $packageLicenses) {
            Copy-Item -Path (Join-Path $packageLicenses "*") -Destination $target -Recurse -Force
        }
    }

    # ISCC resolves a relative /O against its current folder, so pass it absolute.
    $dist = Join-Path $PSScriptRoot "dist"
    Invoke-Native $iscc @(
        "/DMyAppVersion=$version", "/O$dist", "/Q",
        (Join-Path $PSScriptRoot "installer\pdf_compressor.iss")
    )

    # Compress-Archive in PowerShell 5.1 won't overwrite, so start clean.
    $stage = Join-Path $PSScriptRoot "build\portable"
    $zip = Join-Path $dist "PDF-Compressor-$version-portable.zip"
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-Item -LiteralPath $app -Destination $stage -Recurse
    New-Item -ItemType File -Path (Join-Path $stage "PDF Compressor\portable.txt") | Out-Null
    Compress-Archive -Path (Join-Path $stage "PDF Compressor") -DestinationPath $zip

    Write-Host "App:       $app"
    Write-Host "Installer: $(Join-Path $dist "PDF-Compressor-Setup-$version.exe")"
    Write-Host "Portable:  $zip"
}
finally {
    Pop-Location
}
