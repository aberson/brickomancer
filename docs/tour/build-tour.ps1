# build-tour.ps1 - assemble docs/tour/tour.html from tour.template.html.
# Pure ASCII by contract (PowerShell 5.1 decodes a no-BOM .ps1 as cp1252).
# Re-runnable and idempotent: it always rebuilds tour.html from the template.
# Fails loudly if any source asset is missing or any @@TOKEN@@ is left unresolved.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

$TourDir  = $PSScriptRoot
$RepoRoot = Split-Path (Split-Path $TourDir -Parent) -Parent
$Template = Join-Path $TourDir 'tour.template.html'
$OutFile  = Join-Path $TourDir 'tour.html'

# Page budget for the assembled page. Every image and text block is embedded, so the page
# is byte-self-contained; the one remaining network dependency is the webfont stylesheet
# in the template head, which degrades to the declared serif fallback.
$MaxBytes = 1000000

function Fail([string]$msg) {
    Write-Host ("BUILD-TOUR FAILED: " + $msg) -ForegroundColor Red
    exit 1
}

function Require-File([string]$path, [string]$label) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Fail ("missing source asset [" + $label + "]: " + $path)
    }
    return (Resolve-Path -LiteralPath $path).Path
}

function Get-JpegEncoder() {
    foreach ($c in [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders()) {
        if ($c.MimeType -eq 'image/jpeg') { return $c }
    }
    Fail 'no JPEG encoder available on this machine'
}

# Downscale an image to $targetWidth (never upscales) and return a base64 data URI.
function Convert-ImageToDataUri {
    param(
        [string]$Path,
        [int]$TargetWidth,
        [string]$Format,   # 'jpeg' or 'png'
        [int]$Quality      # jpeg only
    )

    $src = [System.Drawing.Image]::FromFile($Path)
    try {
        $w = $src.Width
        $h = $src.Height
        if ($w -gt $TargetWidth) {
            $newW = $TargetWidth
            $newH = [int][Math]::Round($h * ($TargetWidth / [double]$w))
        } else {
            $newW = $w
            $newH = $h
        }
        if ($newH -lt 1) { $newH = 1 }

        $bmp = New-Object -TypeName System.Drawing.Bitmap -ArgumentList $newW, $newH
        try {
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            try {
                $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
                $g.InterpolationMode  = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $g.SmoothingMode      = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $g.PixelOffsetMode    = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                # White matte: the source art is white-background line/flat art.
                $g.Clear([System.Drawing.Color]::White)
                $g.DrawImage($src, 0, 0, $newW, $newH)
            } finally { $g.Dispose() }

            $ms = New-Object -TypeName System.IO.MemoryStream
            try {
                if ($Format -eq 'jpeg') {
                    $enc = Get-JpegEncoder
                    $ep  = New-Object -TypeName System.Drawing.Imaging.EncoderParameters -ArgumentList 1
                    $qualityParam = New-Object -TypeName System.Drawing.Imaging.EncoderParameter -ArgumentList ([System.Drawing.Imaging.Encoder]::Quality), ([int]$Quality)
                    $ep.Param[0] = $qualityParam
                    $bmp.Save($ms, $enc, $ep)
                    $ep.Dispose()
                    $mime = 'image/jpeg'
                } else {
                    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
                    $mime = 'image/png'
                }
                $bytes = $ms.ToArray()
            } finally { $ms.Dispose() }
        } finally { $bmp.Dispose() }
    } finally { $src.Dispose() }

    Write-Host ("  " + (Split-Path $Path -Leaf) + ": " + $w + "x" + $h + " -> " + $newW + "x" + $newH +
                "  " + $bytes.Length + " B encoded (" + $Format + ")")
    return ('data:' + $mime + ';base64,' + [System.Convert]::ToBase64String($bytes))
}

function ConvertTo-HtmlText([string]$s) {
    $s = $s.Replace('&', '&amp;')
    $s = $s.Replace('<', '&lt;')
    $s = $s.Replace('>', '&gt;')
    return $s
}

# Read a fenced block out of a markdown file: start at the first line matching
# $StartPattern, stop at the next line that is exactly a closing code fence.
function Get-FencedBlock {
    param([string]$Path, [string]$StartPattern, [string]$Label)

    $lines = [System.IO.File]::ReadAllLines($Path)
    $start = -1
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match $StartPattern) { $start = $i; break }
    }
    if ($start -lt 0) {
        Fail ("could not locate [" + $Label + "] in " + $Path + " (pattern: " + $StartPattern + ")")
    }
    $end = -1
    for ($j = $start; $j -lt $lines.Length; $j++) {
        if ($lines[$j].Trim() -eq '```') { $end = $j; break }
    }
    if ($end -lt 0) {
        Fail ("unterminated code fence for [" + $Label + "] in " + $Path)
    }
    $block = @($lines[$start..($end - 1)])
    Write-Host ("  " + $Label + ": " + $block.Length + " lines from " + (Split-Path $Path -Leaf))
    return ($block -join "`n")
}

# ---------------------------------------------------------------------------

Write-Host 'build-tour: assembling brickomancer guided tour'
Write-Host ("  repo root: " + (Split-Path $RepoRoot -Leaf))

$null = Require-File $Template 'tour.template.html'

$StarJpg  = Require-File (Join-Path $RepoRoot 'docs/example_input_output/star/input_image/cartoon_star.jpg') 'input star photo'
$SpikeDoc = Require-File (Join-Path $RepoRoot 'docs/investigations/rebuild/04-model-spike-result.md') 'phase 0 spike note'
$HeaderLdr = Require-File (Join-Path $RepoRoot 'tests/fixtures/lpub3d_meta_header.ldr') 'frozen LPub3D header fixture'

Write-Host 'build-tour: loading assets'

# 2x the ~420 px display column so the figure stays crisp on high-DPI screens;
# flat art at q86 costs well under 1% of the page budget.
$starUri = Convert-ImageToDataUri -Path $StarJpg -TargetWidth 840 -Format 'jpeg' -Quality 86

$silhouette = Get-FencedBlock -Path $SpikeDoc -StartPattern '^mesh: verts ' -Label 'spike silhouette'

$headerLines = [System.IO.File]::ReadAllLines($HeaderLdr)
while ($headerLines.Length -gt 0 -and $headerLines[$headerLines.Length - 1].Trim() -eq '') {
    $headerLines = $headerLines[0..($headerLines.Length - 2)]
}
if ($headerLines.Length -eq 0) { Fail 'frozen header fixture is empty' }
$headerText = $headerLines -join "`n"
Write-Host ("  frozen header: " + $headerLines.Length + " lines from lpub3d_meta_header.ldr")

Write-Host 'build-tour: substituting tokens'

$html = [System.IO.File]::ReadAllText($Template)
$html = $html.Replace('@@IMG_INPUT_STAR@@',  $starUri)
$html = $html.Replace('@@SILHOUETTE@@',      (ConvertTo-HtmlText $silhouette))
$html = $html.Replace('@@HEADER_FIXTURE@@',  (ConvertTo-HtmlText $headerText))

$leftover = [regex]::Matches($html, '@@[A-Z0-9_]+@@')
if ($leftover.Count -gt 0) {
    $names = ($leftover | ForEach-Object { $_.Value } | Sort-Object -Unique) -join ', '
    Fail ("unresolved placeholder token(s) left in the page: " + $names)
}

# Budget is checked BEFORE the write, so no failing path can leave a bad tour.html on disk.
$size = [System.Text.Encoding]::UTF8.GetByteCount($html)
Write-Host ''
Write-Host ("build-tour: " + $size + " bytes (budget " + $MaxBytes + ")")
if ($size -gt $MaxBytes) {
    Fail ("assembled page is over budget: " + $size + " > " + $MaxBytes + " bytes; nothing written")
}

$utf8NoBom = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
[System.IO.File]::WriteAllText($OutFile, $html, $utf8NoBom)

$onDisk = (Get-Item -LiteralPath $OutFile).Length
if ($onDisk -ne $size) {
    Fail ("write-back size mismatch: " + $onDisk + " bytes on disk, " + $size + " expected")
}
Write-Host ("build-tour: wrote " + (Split-Path $OutFile -Leaf) + " into " + (Split-Path $TourDir -Leaf) + "/")
Write-Host 'build-tour: OK'
