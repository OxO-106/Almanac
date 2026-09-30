# Draws Almanac's icon (an italic serif "A" on a dark rounded square) at the
# sizes the app needs, and packs the small ones into web\icons\almanac.ico.
# Run again after changing the design; the outputs are committed.
Add-Type -AssemblyName System.Drawing
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$out = "$here\web\icons"
New-Item -ItemType Directory -Force $out | Out-Null
$fonts = New-Object System.Drawing.Text.PrivateFontCollection
$fonts.AddFontFile("$here\web\fonts\LinLibertine_RI.ttf")

function Draw($size) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = "AntiAlias"; $g.TextRenderingHint = "AntiAliasGridFit"
    $r = [int]($size * 0.22); $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc(0, 0, $r, $r, 180, 90); $path.AddArc($size - $r - 1, 0, $r, $r, 270, 90)
    $path.AddArc($size - $r - 1, $size - $r - 1, $r, $r, 0, 90); $path.AddArc(0, $size - $r - 1, $r, $r, 90, 90)
    $g.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(29, 28, 26))), $path)
    $font = New-Object System.Drawing.Font($fonts.Families[0], [single]($size * 0.72), [System.Drawing.FontStyle]::Italic, [System.Drawing.GraphicsUnit]::Pixel)
    $fmt = New-Object System.Drawing.StringFormat; $fmt.Alignment = "Center"; $fmt.LineAlignment = "Center"
    $rect = New-Object System.Drawing.RectangleF(0, [single]($size * 0.04), $size, $size)
    $g.DrawString("A", $font, (New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(251, 250, 247))), $rect, $fmt)
    $dot = [single]($size * 0.11)
    $g.FillEllipse((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(142, 164, 255))), [single]($size * 0.70), [single]($size * 0.16), $dot, $dot)
    $g.Dispose()
    return $bmp
}

$pngs = @()
foreach ($s in 16, 24, 32, 48, 64, 256) {
    $file = "$env:TEMP\almanac-$s.png"; (Draw $s).Save($file, [System.Drawing.Imaging.ImageFormat]::Png); $pngs += , @($s, $file)
}
(Draw 32).Save("$out\favicon-32.png", [System.Drawing.Imaging.ImageFormat]::Png)
(Draw 192).Save("$out\icon-192.png", [System.Drawing.Imaging.ImageFormat]::Png)
(Draw 512).Save("$out\icon-512.png", [System.Drawing.Imaging.ImageFormat]::Png)

# ICO with PNG-compressed images (supported since Windows Vista).
$ms = New-Object System.IO.MemoryStream; $w = New-Object System.IO.BinaryWriter($ms)
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]$pngs.Count)
$offset = 6 + 16 * $pngs.Count; $datas = @()
foreach ($p in $pngs) {
    $data = [System.IO.File]::ReadAllBytes($p[1]); $datas += , $data; $s = $p[0]
    $w.Write([byte]($(if ($s -ge 256) { 0 } else { $s }))); $w.Write([byte]($(if ($s -ge 256) { 0 } else { $s })))
    $w.Write([byte]0); $w.Write([byte]0); $w.Write([uint16]1); $w.Write([uint16]32)
    $w.Write([uint32]$data.Length); $w.Write([uint32]$offset); $offset += $data.Length
}
foreach ($d in $datas) { $w.Write($d) }
[System.IO.File]::WriteAllBytes("$out\almanac.ico", $ms.ToArray())
Write-Host "Icons written to $out"
