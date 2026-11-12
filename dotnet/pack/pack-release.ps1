<#
.SYNOPSIS
  Builds the release artifacts of the EplanMcp script host on a machine with EPLAN installed.

.DESCRIPTION
  EPLAN's API assemblies cannot be redistributed and are absent on hosted CI runners, so releases
  are built here and uploaded as GitHub Release assets. Produces, under dotnet/artifacts/release/:

    EplanMcp-<version>-addon.zip    EPLAN add-on layout: EplanMcp/<version>/BIN + CFG/install.xml,
                                    registered with eplan_register_addon(install_file=...CFG\install.xml)
    EplanMcp-<version>-offline.zip  the offline host (EplanMcp.Host.Offline.exe and its DLLs)
    SHA256SUMS.txt                  checksums of both zips

.PARAMETER EplanVersion
  The EPLAN version to build against (default: the one in Directory.Build.props).
#>
param([string]$EplanVersion = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # dotnet/
# A release must not carry the build machine's paths (they name the user): no debug info, and
# source paths mapped to /_/. --no-incremental so these settings apply to every assembly.
$props = @("-c", "Release", "--no-incremental", "-p:ContinuousIntegrationBuild=true",
           "-p:DebugType=none", "-p:DebugSymbols=false")
if ($EplanVersion) { $props += "-p:EplanVersion=$EplanVersion" }

# The host runs only inside a .NET 8 EPLAN (2027+). Built against an older EPLAN it compiles, but
# binds to Eplan.EplApi.*u.dll and cannot load in 2027, nor in the .NET Framework EPLAN itself.
$probeVersion = $EplanVersion
if (-not $probeVersion) {
    $m = [regex]::Match((Get-Content (Join-Path $root "Directory.Build.props") -Raw), "<EplanVersion[^>]*>([^<]+)</EplanVersion>")
    $probeVersion = $m.Groups[1].Value
}
$bin = Join-Path $env:ProgramW6432 "EPLAN\Platform\$probeVersion\Bin"
if (-not (Test-Path (Join-Path $bin "Eplan.EplApi.BaseNetu.dll"))) {
    throw "No .NET 8 EPLAN at $bin (Eplan.EplApi.BaseNetu.dll missing). Release builds need EPLAN 2027 or newer; pass -EplanVersion."
}

dotnet build (Join-Path $root "src/EplanMcp.Host.AddIn") @props | Out-Host
if ($LASTEXITCODE) { throw "Host build failed." }
dotnet build (Join-Path $root "src/EplanMcp.Host.Offline") @props | Out-Host
if ($LASTEXITCODE) { throw "Offline host build failed." }

$hostDir = Join-Path $root "artifacts/host"
$version = (Get-Content (Join-Path $hostDir "eplanmcp-version.txt") -Raw).Trim()
$out = Join-Path $root "artifacts/release"
$stage = Join-Path $out "stage"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
$addon = Join-Path $stage "EplanMcp/$version"
New-Item -ItemType Directory -Force (Join-Path $addon "BIN"), (Join-Path $addon "CFG") | Out-Null
Copy-Item (Join-Path $hostDir "*") (Join-Path $addon "BIN") -Recurse -Exclude "*.pdb"

$mainVersion = if ($EplanVersion) { $EplanVersion.Substring(0, 4) + ".*" } else { "2027.*" }
@"
<?xml version="1.0" encoding="utf-8"?>
<Settings format="2">
  <CAT name="INSTALL">
    <MOD name="AF">
      <Setting name="ApplicationModifier" type="string" info="Name modification for specific application configuration">
        <Val>EplanMcp</Val>
      </Setting>
    </MOD>
  </CAT>
  <CAT name="STATION">
    <MOD name="SYSTEM">
      <LEV1 name="EplanMcp">
        <Setting name="XMLPath" type="string" info="patched path to install.xml"><Val>CFG\</Val></Setting>
        <Setting name="Version" type="string" info="version nr of this addon"><Val>$version</Val></Setting>
        <LEV2 name="MainVersion">
          <LEV3 name="Basic">
            <Setting name="Licences" type="string" info="Licence of Main Product to identify it"><Val>700</Val></Setting>
            <Setting name="Versions" type="string" info="Version of Main Product to identify it"><Val>$mainVersion</Val></Setting>
          </LEV3>
        </LEV2>
      </LEV1>
    </MOD>
    <MOD name="AF">
      <LEV1 name="ApiModules">
        <Setting name="EplanMcp" type="string" info="">
          <Val>EplanMcp.Host.AddIn</Val>
        </Setting>
      </LEV1>
    </MOD>
  </CAT>
</Settings>
"@ | Set-Content -Encoding utf8 (Join-Path $addon "CFG/install.xml")

$offlineStage = Join-Path $stage "offline"
New-Item -ItemType Directory -Force $offlineStage | Out-Null
Copy-Item (Join-Path $root "artifacts/offline/*") $offlineStage -Recurse -Exclude "*.pdb"

# Refuse to package anything that still names this machine's user or folders.
$needles = @($env:USERPROFILE, (Split-Path -Parent $root), $env:USERNAME) | Where-Object { $_ -and $_.Length -ge 3 }
$leaks = Get-ChildItem $stage -Recurse -File | Where-Object {
    $bytes = [IO.File]::ReadAllBytes($_.FullName)
    $text = [Text.Encoding]::ASCII.GetString($bytes) + [Text.Encoding]::Unicode.GetString($bytes)
    $needles | Where-Object { $text.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 }
}
if ($leaks) { throw "Release files contain local paths or the user name: $($leaks.Name -join ', ')" }

$addonZip = Join-Path $out "EplanMcp-$version-addon.zip"
$offlineZip = Join-Path $out "EplanMcp-$version-offline.zip"
Compress-Archive -Path (Join-Path $stage "EplanMcp") -DestinationPath $addonZip
Compress-Archive -Path (Join-Path $offlineStage "*") -DestinationPath $offlineZip
$sums = Get-FileHash $addonZip, $offlineZip -Algorithm SHA256 |
    ForEach-Object { "{0}  {1}" -f $_.Hash.ToLowerInvariant(), (Split-Path $_.Path -Leaf) }
$sums | Set-Content -Encoding ascii (Join-Path $out "SHA256SUMS.txt")
Remove-Item $stage -Recurse -Force
Write-Host "Release artifacts in $out"
$sums | Write-Host
# Host releases use their own tag line (host-v<version>, see HOST_TAG_PREFIX in
# python/mcp_server/api/actions/scripthost.py): it never triggers the server's release workflow.
Write-Host ""
Write-Host "Publish with:"
Write-Host ("  gh release create host-v$version `"$addonZip`" `"$offlineZip`" `"$(Join-Path $out 'SHA256SUMS.txt')`" " +
            "--title `"Script host $version`" --notes `"EplanMcp script host $version, built against EPLAN $probeVersion.`"")
