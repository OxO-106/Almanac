# Draws Almanac's icon (an italic serif "A" over a pale rule, on a slate
# rounded square: the palette's #536B78 and #ACCBE1) at the sizes the app
# needs, and packs the small ones into web\icons\almanac.ico.
# Run again after changing the design; the outputs are committed.
Add-Type -AssemblyName System.Drawing
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$out = "$here\web\icons"
New-Item -ItemType Directory -Force $out | Out-Null
$fonts = New-Object System.Drawing.Text.PrivateFontCollection
$fonts.AddFontFile("$here\web\fonts\LinLibertine_RI.ttf")
function Color($hex) { [System.Drawing.ColorTranslator]::FromHtml($hex) }

function Draw($size, [switch]$Full) {
    # $Full: fill the whole square (iOS and Android round the corners themselves)
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = "AntiAlias"; $g.PixelOffsetMode = "HighQuality"
    $s = [single]$size
    $slate = New-Object System.Drawing.SolidBrush(Color "#536B78")
    if ($Full) { $g.FillRectangle($slate, 0, 0, $s, $s) } else {
        $r = $s * 0.44; $p = New-Object System.Drawing.Drawing2D.GraphicsPath
        $p.AddArc(0, 0, $r, $r, 180, 90); $p.AddArc($s - $r, 0, $r, $r, 270, 90)
        $p.AddArc($s - $r, $s - $r, $r, $r, 0, 90); $p.AddArc(0, $s - $r, $r, $r, 90, 90); $p.CloseFigure()
        $g.FillPath($slate, $p)
    }
    # the rule: a marked line on the page
    $h = [math]::Max(1, [math]::Round($s * 0.07))
    $g.FillRectangle((New-Object System.Drawing.SolidBrush(Color "#ACCBE1")), [single][math]::Round($s * 0.24), [single][math]::Round($s * 0.78), [single][math]::Round($s * 0.52), [single]$h)
    # the letter, as a path so small sizes can be thickened
    $a = New-Object System.Drawing.Drawing2D.GraphicsPath
    $fmt = New-Object System.Drawing.StringFormat; $fmt.Alignment = "Center"; $fmt.LineAlignment = "Center"
    $a.AddString("A", $fonts.Families[0], [int][System.Drawing.FontStyle]::Italic, $s * 0.72, (New-Object System.Drawing.RectangleF(($s * -0.02), ($s * -0.06), $s, $s)), $fmt)
    $white = Color "#FFFFFF"
    $g.FillPath((New-Object System.Drawing.SolidBrush($white)), $a)
    if ($size -le 48) { $g.DrawPath((New-Object System.Drawing.Pen($white, [single]($s * 0.035))), $a) }
    $g.Dispose()
    return $bmp
}

function Badge($size) {
    # Android's small notification icon: the letter alone, white on transparent
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g = [System.Drawing.Graphics]::FromImage($bmp); $g.SmoothingMode = "AntiAlias"; $s = [single]$size
    $a = New-Object System.Drawing.Drawing2D.GraphicsPath
    $fmt = New-Object System.Drawing.StringFormat; $fmt.Alignment = "Center"; $fmt.LineAlignment = "Center"
    $a.AddString("A", $fonts.Families[0], [int][System.Drawing.FontStyle]::Italic, $s * 0.95, (New-Object System.Drawing.RectangleF(0, 0, $s, $s)), $fmt)
    $g.FillPath([System.Drawing.Brushes]::White, $a); $g.Dispose()
    return $bmp
}

function Pixel16 {
    # The tray's 16px icon, placed pixel by pixel: a drawn italic "A" at this size is
    # mostly half-grey edge pixels and looks blurred. Same square, letter and rule.
    $map = @(
        "..ssssssssssss..",
        ".ssssssssssssss.",
        "sssssssWWsssssss",
        "ssssssWWWWssssss",
        "ssssssWWWWssssss",
        "sssssWWssWWsssss",
        "sssssWWssWWsssss",
        "ssssWWssssWWssss",
        "ssssWWWWWWWWssss",
        "sssWWssssssWWsss",
        "sssWWssssssWWsss",
        "ssWWssssssssWWss",
        "ssssssssssssssss",
        "ssssrrrrrrrrssss",
        ".ssssssssssssss.",
        "..ssssssssssss..")
    $colors = @{ "s" = (Color "#536B78"); "W" = (Color "#FFFFFF"); "r" = (Color "#ACCBE1") }
    $bmp = New-Object System.Drawing.Bitmap(16, 16)
    for ($y = 0; $y -lt 16; $y++) { for ($x = 0; $x -lt 16; $x++) {
        $c = $map[$y][$x]; if ($c -ne ".") { $bmp.SetPixel($x, $y, $colors[[string]$c]) } } }
    return $bmp
}

$pngs = @()
foreach ($s in 16, 24, 32, 48, 64, 256) {
    $img = if ($s -eq 16) { Pixel16 } else { Draw $s }
    $file = "$env:TEMP\almanac-$s.png"; $img.Save($file, [System.Drawing.Imaging.ImageFormat]::Png); $pngs += , @($s, $file)
}
(Pixel16).Save("$out\favicon-16.png", [System.Drawing.Imaging.ImageFormat]::Png)  # a window's title bar: crisp, not the 32 shrunk
(Draw 32).Save("$out\favicon-32.png", [System.Drawing.Imaging.ImageFormat]::Png)
(Draw 180 -Full).Save("$out\apple-touch-icon.png", [System.Drawing.Imaging.ImageFormat]::Png)
(Draw 192).Save("$out\icon-192.png", [System.Drawing.Imaging.ImageFormat]::Png)
(Draw 512).Save("$out\icon-512.png", [System.Drawing.Imaging.ImageFormat]::Png)
(Badge 96).Save("$out\badge-96.png", [System.Drawing.Imaging.ImageFormat]::Png)
(Draw 512 -Full).Save("$out\icon-maskable-512.png", [System.Drawing.Imaging.ImageFormat]::Png)

# ICO: 256px as PNG, smaller sizes as 32-bit bitmaps (System.Drawing.Icon,
# which the tray uses, can't draw small PNG frames).
function Dib($file, $s) {
    $bmp = New-Object System.Drawing.Bitmap($file)
    $m = New-Object System.IO.MemoryStream; $b = New-Object System.IO.BinaryWriter($m)
    $mask = [int]([math]::Ceiling($s / 32) * 4) * $s
    $b.Write([uint32]40); $b.Write([int32]$s); $b.Write([int32]($s * 2)); $b.Write([uint16]1); $b.Write([uint16]32)
    $b.Write([uint32]0); $b.Write([uint32]($s * $s * 4 + $mask)); $b.Write([int32]0); $b.Write([int32]0); $b.Write([uint32]0); $b.Write([uint32]0)
    for ($y = $s - 1; $y -ge 0; $y--) { for ($x = 0; $x -lt $s; $x++) {
        $c = $bmp.GetPixel($x, $y); $b.Write([byte]$c.B); $b.Write([byte]$c.G); $b.Write([byte]$c.R); $b.Write([byte]$c.A) } }
    $b.Write((New-Object byte[] $mask)); $bmp.Dispose()
    return , $m.ToArray()
}
$ms = New-Object System.IO.MemoryStream; $w = New-Object System.IO.BinaryWriter($ms)
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]$pngs.Count)
$offset = 6 + 16 * $pngs.Count; $datas = @()
foreach ($p in $pngs) {
    $s = $p[0]
    $data = if ($s -ge 256) { [System.IO.File]::ReadAllBytes($p[1]) } else { Dib $p[1] $s }
    $datas += , $data
    $w.Write([byte]($(if ($s -ge 256) { 0 } else { $s }))); $w.Write([byte]($(if ($s -ge 256) { 0 } else { $s })))
    $w.Write([byte]0); $w.Write([byte]0); $w.Write([uint16]1); $w.Write([uint16]32)
    $w.Write([uint32]$data.Length); $w.Write([uint32]$offset); $offset += $data.Length
}
foreach ($d in $datas) { $w.Write($d) }
[System.IO.File]::WriteAllBytes("$out\almanac.ico", $ms.ToArray())
Write-Host "Icons written to $out"
