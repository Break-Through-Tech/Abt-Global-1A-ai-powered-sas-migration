param(
    [string]$Script = "main.py",
    [string]$GeneratedDirectory = "generated",
    [string]$InputDirectory = "data/Project_1/Starrating",
    [string]$OutputDirectory = "reports/runner-output",
    [string]$ResultDirectory = "reports/runner-results",
    [ValidateRange(1, 600)]
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path

function Resolve-ProjectDirectory {
    param(
        [string]$Value,
        [switch]$Create
    )

    $candidate = if ([System.IO.Path]::IsPathRooted($Value)) {
        [System.IO.Path]::GetFullPath($Value)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Value))
    }

    if ($Create) {
        New-Item -ItemType Directory -Force -Path $candidate | Out-Null
    } elseif (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "Runner directory does not exist: $candidate"
    }

    $resolvedCandidate = (Resolve-Path -LiteralPath $candidate).Path
    $rootWithSeparator = $projectRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolvedCandidate.StartsWith(
        $rootWithSeparator,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Runner directories must stay beneath the repository root: $Value"
    }
    return $resolvedCandidate
}

function Test-PathsOverlap {
    param(
        [string]$Left,
        [string]$Right
    )

    $leftPath = $Left.TrimEnd('\', '/')
    $rightPath = $Right.TrimEnd('\', '/')
    $separator = [System.IO.Path]::DirectorySeparatorChar
    return $leftPath.Equals($rightPath, [System.StringComparison]::OrdinalIgnoreCase) -or
        $leftPath.StartsWith($rightPath + $separator, [System.StringComparison]::OrdinalIgnoreCase) -or
        $rightPath.StartsWith($leftPath + $separator, [System.StringComparison]::OrdinalIgnoreCase)
}

$sourcePath = Resolve-ProjectDirectory $GeneratedDirectory
$inputPath = Resolve-ProjectDirectory $InputDirectory
$outputPath = Resolve-ProjectDirectory $OutputDirectory -Create
$resultDirectoryPath = Resolve-ProjectDirectory $ResultDirectory -Create

if ((Test-PathsOverlap $sourcePath $inputPath) -or
    (Test-PathsOverlap $sourcePath $outputPath) -or
    (Test-PathsOverlap $inputPath $outputPath) -or
    (Test-PathsOverlap $sourcePath $resultDirectoryPath) -or
    (Test-PathsOverlap $inputPath $resultDirectoryPath) -or
    (Test-PathsOverlap $outputPath $resultDirectoryPath)) {
    throw "Source, input, output, and result directories must not overlap."
}

$forbiddenDirectories = @(
    (Join-Path $projectRoot "data\Project_1\SAS Output CSV"),
    (Join-Path $projectRoot "data\Project_1\SAS Output")
)
foreach ($forbiddenDirectory in $forbiddenDirectories) {
    foreach ($candidate in @($sourcePath, $inputPath, $outputPath, $resultDirectoryPath)) {
        if (Test-PathsOverlap $candidate $forbiddenDirectory) {
            throw "Runner directory overlaps a trusted golden-output path: $candidate"
        }
    }
}

$scriptPath = [System.IO.Path]::GetFullPath((Join-Path $sourcePath $Script))
$sourceWithSeparator = $sourcePath.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (-not $scriptPath.StartsWith($sourceWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Script must stay beneath the generated directory: $Script"
}
if (-not $Script.EndsWith(".py", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Script must be a relative .py path: $Script"
}
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "Generated entry point does not exist: $scriptPath"
}

$env:SASGUARD_GENERATED_DIR = $sourcePath
$env:SASGUARD_INPUT_DIR = $inputPath
$env:SASGUARD_OUTPUT_DIR = $outputPath
$env:SASGUARD_SCRIPT = $Script.Replace('\', '/')
$env:SASGUARD_TIMEOUT_SECONDS = $TimeoutSeconds.ToString()

Push-Location $projectRoot
try {
    docker compose --profile runner build runner
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    $resultJson = docker compose --profile runner run --rm runner | Out-String
    $runExitCode = $LASTEXITCODE
    if ($runExitCode -ne 0) {
        exit $runExitCode
    }

    $resultPath = Join-Path $resultDirectoryPath "execution-result.json"
    [System.IO.File]::WriteAllText(
        $resultPath,
        $resultJson,
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Output "Execution result written to $resultPath"
    exit 0
} finally {
    Pop-Location
}
