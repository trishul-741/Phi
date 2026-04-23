Add-Type -AssemblyName System.Drawing

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-ColorHex {
    param(
        [Parameter(Mandatory = $true)][string]$Hex,
        [int]$Alpha = 255
    )

    $value = $Hex.TrimStart("#")
    return [System.Drawing.Color]::FromArgb(
        $Alpha,
        [Convert]::ToInt32($value.Substring(0, 2), 16),
        [Convert]::ToInt32($value.Substring(2, 2), 16),
        [Convert]::ToInt32($value.Substring(4, 2), 16)
    )
}

function New-PointF {
    param([double]$X, [double]$Y)
    return [System.Drawing.PointF]::new([float]$X, [float]$Y)
}

function New-RectF {
    param([double]$X, [double]$Y, [double]$Width, [double]$Height)
    return [System.Drawing.RectangleF]::new([float]$X, [float]$Y, [float]$Width, [float]$Height)
}

function Get-ShieldPath {
    param(
        [double]$Size,
        [double]$Scale = 1.0
    )

    $cx = $Size * 0.5
    $cy = $Size * 0.5
    $shape = @(
        @(0.50, 0.08),
        @(0.82, 0.20),
        @(0.80, 0.56),
        @(0.66, 0.80),
        @(0.50, 0.92),
        @(0.34, 0.80),
        @(0.20, 0.56),
        @(0.18, 0.20)
    )

    $points = New-Object 'System.Drawing.PointF[]' $shape.Count
    for ($i = 0; $i -lt $shape.Count; $i++) {
        $px = $shape[$i][0] * $Size
        $py = $shape[$i][1] * $Size
        $points[$i] = New-PointF (
            $cx + (($px - $cx) * $Scale)
        ) (
            $cy + (($py - $cy) * $Scale)
        )
    }

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddClosedCurve($points, 0.35)
    return $path
}

function Add-GlowFill {
    param(
        [System.Drawing.Graphics]$Graphics,
        [double]$Size,
        [System.Drawing.Color]$Color
    )

    foreach ($step in 0..3) {
        $scale = 1.04 + ($step * 0.03)
        $alpha = [Math]::Max(16, 90 - ($step * 22))
        $path = Get-ShieldPath -Size $Size -Scale $scale
        $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb($alpha, $Color))
        $Graphics.FillPath($brush, $path)
        $brush.Dispose()
        $path.Dispose()
    }
}

function New-Graphics {
    param([System.Drawing.Bitmap]$Bitmap)
    $graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.Clear([System.Drawing.Color]::Transparent)
    return $graphics
}

function Draw-ShieldBase {
    param(
        [System.Drawing.Graphics]$Graphics,
        [double]$Size,
        [string]$Concept
    )

    $electric = New-ColorHex "#118BFF"
    $cyan = New-ColorHex "#2DE0FF"
    $navy = New-ColorHex "#08111D"
    $mid = New-ColorHex "#102A59"
    $panel = New-ColorHex "#1B5FBE" 52
    $warningGlow = New-ColorHex "#FF5B43"

    $glowColor = if ($Concept -eq "warning") { $warningGlow } else { $cyan }
    Add-GlowFill -Graphics $Graphics -Size $Size -Color $glowColor

    $outerPath = Get-ShieldPath -Size $Size -Scale 1.0
    $innerPath = Get-ShieldPath -Size $Size -Scale 0.84

    $outerBrush = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        (New-RectF 0 0 $Size $Size),
        $electric,
        (New-ColorHex "#0B1D38"),
        90.0
    )
    $outerBlend = New-Object System.Drawing.Drawing2D.ColorBlend
    $outerBlend.Colors = [System.Drawing.Color[]]@(
        $cyan,
        $electric,
        (New-ColorHex "#0C2E6B"),
        (New-ColorHex "#07111E")
    )
    $outerBlend.Positions = [single[]](0.0, 0.18, 0.55, 1.0)
    $outerBrush.InterpolationColors = $outerBlend
    $Graphics.FillPath($outerBrush, $outerPath)

    $innerBrush = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        (New-RectF ($Size * 0.14) ($Size * 0.14) ($Size * 0.72) ($Size * 0.72)),
        $mid,
        $navy,
        115.0
    )
    $innerBlend = New-Object System.Drawing.Drawing2D.ColorBlend
    $innerBlend.Colors = [System.Drawing.Color[]]@(
        (New-ColorHex "#163E87"),
        (New-ColorHex "#0B2146"),
        (New-ColorHex "#08111D")
    )
    $innerBlend.Positions = [single[]](0.0, 0.42, 1.0)
    $innerBrush.InterpolationColors = $innerBlend
    $Graphics.FillPath($innerBrush, $innerPath)

    $leftPanel = New-Object System.Drawing.Drawing2D.GraphicsPath
    $leftPanel.AddPolygon([System.Drawing.PointF[]]@(
        (New-PointF ($Size * 0.31) ($Size * 0.20)),
        (New-PointF ($Size * 0.50) ($Size * 0.11)),
        (New-PointF ($Size * 0.50) ($Size * 0.88)),
        (New-PointF ($Size * 0.28) ($Size * 0.72))
    ))
    $panelBrush = New-Object System.Drawing.SolidBrush $panel
    $Graphics.FillPath($panelBrush, $leftPanel)

    $shinePen = New-Object System.Drawing.Pen ((New-ColorHex "#FFFFFF" 72), [float]($Size * 0.015))
    $shinePen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $Graphics.DrawLine($shinePen, $Size * 0.50, $Size * 0.12, $Size * 0.50, $Size * 0.83)

    $outerPen = New-Object System.Drawing.Pen ((New-ColorHex "#0A1A32" 190), [float]($Size * 0.022))
    $outerPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $Graphics.DrawPath($outerPen, $outerPath)

    $innerPen = New-Object System.Drawing.Pen ((New-ColorHex "#D7F8FF" 80), [float]($Size * 0.012))
    $innerPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $Graphics.DrawPath($innerPen, $innerPath)

    $topHighlight = New-Object System.Drawing.Drawing2D.GraphicsPath
    $topHighlight.AddClosedCurve([System.Drawing.PointF[]]@(
        (New-PointF ($Size * 0.30) ($Size * 0.22)),
        (New-PointF ($Size * 0.50) ($Size * 0.15)),
        (New-PointF ($Size * 0.70) ($Size * 0.22)),
        (New-PointF ($Size * 0.50) ($Size * 0.27))
    ), 0.35)
    $topBrush = New-Object System.Drawing.SolidBrush ((New-ColorHex "#9EF8FF" 44))
    $Graphics.FillPath($topBrush, $topHighlight)

    $outerBrush.Dispose()
    $innerBrush.Dispose()
    $panelBrush.Dispose()
    $shinePen.Dispose()
    $outerPen.Dispose()
    $innerPen.Dispose()
    $topBrush.Dispose()
    $leftPanel.Dispose()
    $topHighlight.Dispose()
    $outerPath.Dispose()
    $innerPath.Dispose()
}

function Draw-CheckConcept {
    param([System.Drawing.Graphics]$Graphics, [double]$Size)

    $glowPen = New-Object System.Drawing.Pen ((New-ColorHex "#36E6FF" 108), [float]($Size * 0.17))
    $glowPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $glowPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $glowPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round

    $mainPen = New-Object System.Drawing.Pen ((New-ColorHex "#F7FBFF"), [float]($Size * 0.11))
    $mainPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $mainPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $mainPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round

    $checkPath = New-Object System.Drawing.Drawing2D.GraphicsPath
    $checkPath.AddLines([System.Drawing.PointF[]]@(
        (New-PointF ($Size * 0.30) ($Size * 0.55)),
        (New-PointF ($Size * 0.44) ($Size * 0.69)),
        (New-PointF ($Size * 0.70) ($Size * 0.40))
    ))

    $ringPen = New-Object System.Drawing.Pen ((New-ColorHex "#36E6FF" 58), [float]($Size * 0.04))
    $Graphics.DrawEllipse($ringPen, $Size * 0.24, $Size * 0.23, $Size * 0.52, $Size * 0.52)
    $Graphics.DrawPath($glowPen, $checkPath)
    $Graphics.DrawPath($mainPen, $checkPath)

    $glowPen.Dispose()
    $mainPen.Dispose()
    $ringPen.Dispose()
    $checkPath.Dispose()
}

function Draw-WarningConcept {
    param([System.Drawing.Graphics]$Graphics, [double]$Size)

    $hookPen = New-Object System.Drawing.Pen ((New-ColorHex "#F5FAFF"), [float]($Size * 0.085))
    $hookPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $hookPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $hookPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round

    $hookPath = New-Object System.Drawing.Drawing2D.GraphicsPath
    $hookPath.AddLine($Size * 0.58, $Size * 0.28, $Size * 0.58, $Size * 0.55)
    $hookPath.AddArc($Size * 0.42, $Size * 0.48, $Size * 0.22, $Size * 0.22, 315, 220)
    $hookPath.AddLine($Size * 0.46, $Size * 0.70, $Size * 0.52, $Size * 0.63)

    $slashGlowPen = New-Object System.Drawing.Pen ((New-ColorHex "#FF5E42" 100), [float]($Size * 0.15))
    $slashGlowPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $slashGlowPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round

    $slashPen = New-Object System.Drawing.Pen ((New-ColorHex "#FF5B43"), [float]($Size * 0.10))
    $slashPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $slashPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round

    $ringPen = New-Object System.Drawing.Pen ((New-ColorHex "#FF8B2D"), [float]($Size * 0.055))
    $ringPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round

    $Graphics.DrawEllipse($ringPen, $Size * 0.24, $Size * 0.22, $Size * 0.52, $Size * 0.52)
    $Graphics.DrawPath($hookPen, $hookPath)
    $Graphics.DrawLine($slashGlowPen, $Size * 0.34, $Size * 0.30, $Size * 0.72, $Size * 0.68)
    $Graphics.DrawLine($slashPen, $Size * 0.34, $Size * 0.30, $Size * 0.72, $Size * 0.68)

    $warningDot = New-Object System.Drawing.SolidBrush ((New-ColorHex "#FFD6C4"))
    $Graphics.FillEllipse($warningDot, $Size * 0.53, $Size * 0.20, $Size * 0.06, $Size * 0.06)

    $hookPen.Dispose()
    $slashGlowPen.Dispose()
    $slashPen.Dispose()
    $ringPen.Dispose()
    $warningDot.Dispose()
    $hookPath.Dispose()
}

function Draw-MonogramConcept {
    param([System.Drawing.Graphics]$Graphics, [double]$Size)

    $fontName = "Segoe UI"
    $fontFamily = New-Object System.Drawing.FontFamily($fontName)
    $fontStyle = [System.Drawing.FontStyle]::Bold
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddString(
        "P",
        $fontFamily,
        [int]$fontStyle,
        [float]($Size * 0.48),
        (New-RectF ($Size * 0.21) ($Size * 0.15) ($Size * 0.58) ($Size * 0.62)),
        ([System.Drawing.StringFormat]::GenericTypographic)
    )

    $glowBrush = New-Object System.Drawing.SolidBrush ((New-ColorHex "#37E2FF" 70))
    $Graphics.TranslateTransform([float]($Size * 0.004), [float]($Size * 0.010))
    $Graphics.FillPath($glowBrush, $path)
    $Graphics.ResetTransform()

    $textBrush = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        (New-RectF ($Size * 0.28) ($Size * 0.18) ($Size * 0.42) ($Size * 0.60)),
        (New-ColorHex "#FFFFFF"),
        (New-ColorHex "#9FDFFF"),
        90.0
    )
    $Graphics.FillPath($textBrush, $path)

    $accentPath = New-Object System.Drawing.Drawing2D.GraphicsPath
    $accentPath.AddPolygon([System.Drawing.PointF[]]@(
        (New-PointF ($Size * 0.42) ($Size * 0.52)),
        (New-PointF ($Size * 0.59) ($Size * 0.52)),
        (New-PointF ($Size * 0.47) ($Size * 0.81)),
        (New-PointF ($Size * 0.42) ($Size * 0.76))
    ))
    $accentBrush = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        (New-RectF ($Size * 0.42) ($Size * 0.52) ($Size * 0.17) ($Size * 0.30)),
        (New-ColorHex "#34DFFF"),
        (New-ColorHex "#1094FF"),
        90.0
    )
    $Graphics.FillPath($accentBrush, $accentPath)

    $circuitPen = New-Object System.Drawing.Pen ((New-ColorHex "#2DE0FF" 140), [float]($Size * 0.022))
    $circuitPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $circuitPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $Graphics.DrawLines($circuitPen, [System.Drawing.PointF[]]@(
        (New-PointF ($Size * 0.30) ($Size * 0.34)),
        (New-PointF ($Size * 0.26) ($Size * 0.38)),
        (New-PointF ($Size * 0.26) ($Size * 0.58)),
        (New-PointF ($Size * 0.32) ($Size * 0.64))
    ))
    $Graphics.DrawLines($circuitPen, [System.Drawing.PointF[]]@(
        (New-PointF ($Size * 0.61) ($Size * 0.69)),
        (New-PointF ($Size * 0.72) ($Size * 0.69)),
        (New-PointF ($Size * 0.76) ($Size * 0.64))
    ))

    foreach ($dot in @(
        @(0.30, 0.34),
        @(0.32, 0.64),
        @(0.76, 0.64)
    )) {
        $dotBrush = New-Object System.Drawing.SolidBrush ((New-ColorHex "#3CE3FF"))
        $Graphics.FillEllipse($dotBrush, $Size * ($dot[0] - 0.02), $Size * ($dot[1] - 0.02), $Size * 0.04, $Size * 0.04)
        $dotBrush.Dispose()
    }

    $textOutline = New-Object System.Drawing.Pen ((New-ColorHex "#E3FAFF" 40), [float]($Size * 0.010))
    $Graphics.DrawPath($textOutline, $path)

    $textOutline.Dispose()
    $circuitPen.Dispose()
    $accentBrush.Dispose()
    $accentPath.Dispose()
    $textBrush.Dispose()
    $glowBrush.Dispose()
    $path.Dispose()
    $fontFamily.Dispose()
}

function Render-Concept {
    param(
        [string]$Concept,
        [int]$Size
    )

    $renderSize = [Math]::Max(256, $Size * 8)
    $bitmap = New-Object System.Drawing.Bitmap $renderSize, $renderSize
    $graphics = New-Graphics -Bitmap $bitmap

    Draw-ShieldBase -Graphics $graphics -Size $renderSize -Concept $Concept
    switch ($Concept) {
        "trust" { Draw-CheckConcept -Graphics $graphics -Size $renderSize }
        "warning" { Draw-WarningConcept -Graphics $graphics -Size $renderSize }
        "monogram" { Draw-MonogramConcept -Graphics $graphics -Size $renderSize }
        default { throw "Unknown concept: $Concept" }
    }

    $final = New-Object System.Drawing.Bitmap $Size, $Size
    $finalGraphics = New-Graphics -Bitmap $final
    $finalGraphics.DrawImage($bitmap, 0, 0, $Size, $Size)

    $graphics.Dispose()
    $finalGraphics.Dispose()
    $bitmap.Dispose()
    return $final
}

function Save-ConceptFamily {
    param(
        [string]$Root,
        [string]$Concept,
        [string]$FolderName
    )

    $conceptDir = Join-Path $Root $FolderName
    New-Item -ItemType Directory -Path $conceptDir -Force | Out-Null

    foreach ($size in @(16, 32, 48, 128)) {
        $bitmap = Render-Concept -Concept $Concept -Size $size
        $path = Join-Path $conceptDir ("icon-{0}.png" -f $size)
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()
    }

    $master = Render-Concept -Concept $Concept -Size 512
    $master.Save((Join-Path $conceptDir "master.png"), [System.Drawing.Imaging.ImageFormat]::Png)
    $master.Dispose()
}

function Save-PreviewSheet {
    param([string]$Root)

    $sheet = New-Object System.Drawing.Bitmap 1200, 420
    $graphics = New-Graphics -Bitmap $sheet

    $concepts = @(
        @{ Name = "trust"; X = 30; Title = "Shield + Check" },
        @{ Name = "warning"; X = 420; Title = "Shield + Warning" },
        @{ Name = "monogram"; X = 810; Title = "Shield + P" }
    )

    foreach ($concept in $concepts) {
        $cardBrush = New-Object System.Drawing.SolidBrush ((New-ColorHex "#07111D" 22))
        $graphics.FillRectangle($cardBrush, $concept.X, 20, 360, 360)
        $cardBrush.Dispose()

        $icon = Render-Concept -Concept $concept.Name -Size 320
        $graphics.DrawImage($icon, $concept.X + 20, 30, 320, 320)
        $icon.Dispose()
    }

    $sheet.Save((Join-Path $Root "phishguard-icon-family-preview.png"), [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $sheet.Dispose()
}

$iconsRoot = Join-Path $PSScriptRoot "..\\icons"
$iconsRoot = [System.IO.Path]::GetFullPath($iconsRoot)

Save-ConceptFamily -Root $iconsRoot -Concept "trust" -FolderName "concept-1-shield-check"
Save-ConceptFamily -Root $iconsRoot -Concept "warning" -FolderName "concept-2-shield-warning"
Save-ConceptFamily -Root $iconsRoot -Concept "monogram" -FolderName "concept-3-shield-monogram"
Save-PreviewSheet -Root $iconsRoot

# Set concept 1 as the default extension icon family.
Copy-Item (Join-Path $iconsRoot "concept-1-shield-check\\icon-16.png") (Join-Path $iconsRoot "icon-16.png") -Force
Copy-Item (Join-Path $iconsRoot "concept-1-shield-check\\icon-32.png") (Join-Path $iconsRoot "icon-32.png") -Force
Copy-Item (Join-Path $iconsRoot "concept-1-shield-check\\icon-48.png") (Join-Path $iconsRoot "icon-48.png") -Force
Copy-Item (Join-Path $iconsRoot "concept-1-shield-check\\icon-128.png") (Join-Path $iconsRoot "icon-128.png") -Force
Copy-Item (Join-Path $iconsRoot "concept-1-shield-check\\icon-128.png") (Join-Path $iconsRoot "icon.png") -Force
