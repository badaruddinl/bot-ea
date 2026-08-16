function ConvertTo-GoldMResearchDate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,
        [Parameter(Mandatory = $true)]
        [string]$FieldName
    )

    $parsed = [datetime]::MinValue
    [string[]]$formats = @('yyyy.MM.dd', 'yyyy-MM-dd')
    $style = [System.Globalization.DateTimeStyles]::None
    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    if (-not [datetime]::TryParseExact($Value, $formats, $culture, $style, [ref]$parsed)) {
        throw "$FieldName must use yyyy.MM.dd or yyyy-MM-dd; received '$Value'."
    }
    return $parsed.Date
}

function Get-GoldMResearchPolicy {
    $policyPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'config\goldm-research-policy.json'
    if (-not (Test-Path -LiteralPath $policyPath)) {
        throw "GOLDm research policy was not found: $policyPath"
    }
    $policy = Get-Content -Raw -LiteralPath $policyPath | ConvertFrom-Json
    if ($policy.schema_version -ne 1 -or $policy.range_semantics -ne 'half-open [from, to)') {
        throw "Unsupported GOLDm research policy schema or range semantics: $policyPath"
    }
    return $policy
}

function Stop-GoldMLegacyTerminalResearch {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    throw "$Label is disabled: direct MT5 terminal/tester history is not a registered dataset. Use scripts/run-goldm-research-safe.py with an approved --dataset-manifest and registered run/fold evidence."
}

function Assert-GoldMResearchRange {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$FromDate,
        [Parameter(Mandatory = $true)]
        [string]$ToDate,
        [ValidateSet('Development', 'Validation', 'Diagnostic', 'BlindOos')]
        [string]$Purpose = 'Diagnostic',
        [ValidateSet('DEVELOPMENT_SELECTION', 'LOCKED_LEGACY_VALIDATION', 'DIAGNOSTIC_ONLY', 'BLIND_OOS')]
        [string]$StatisticalClassification = '',
        [string]$Label = 'research run'
    )

    $policy = Get-GoldMResearchPolicy
    $from = ConvertTo-GoldMResearchDate -Value $FromDate -FieldName 'FromDate'
    $to = ConvertTo-GoldMResearchDate -Value $ToDate -FieldName 'ToDate'
    if ($from -ge $to) {
        throw "$Label has an invalid half-open range [$FromDate, $ToDate): FromDate must be earlier than ToDate."
    }

    # All project ranges use half-open semantics: FromDate is included and ToDate is excluded.
    $quarantineFrom = ConvertTo-GoldMResearchDate -Value $policy.quarantine.from -FieldName 'policy.quarantine.from'
    $quarantineTo = ConvertTo-GoldMResearchDate -Value $policy.quarantine.to -FieldName 'policy.quarantine.to'
    if ($from -lt $quarantineTo -and $to -gt $quarantineFrom) {
        throw "$Label range [$FromDate, $ToDate) intersects the protected quarantine [$($policy.quarantine.from), $($policy.quarantine.to)). No backtest, tuning, selection, validation, or OOS run is permitted."
    }

    $requiredClassification = switch ($Purpose) {
        'Development' { 'DEVELOPMENT_SELECTION' }
        'Validation' { 'LOCKED_LEGACY_VALIDATION' }
        'Diagnostic' { 'DIAGNOSTIC_ONLY' }
        'BlindOos' { 'BLIND_OOS' }
    }
    if (-not $StatisticalClassification) {
        throw "$Label statistical classification is required; purpose $Purpose requires $requiredClassification."
    }
    if ($StatisticalClassification -ne $requiredClassification) {
        throw "$Label purpose $Purpose requires statistical classification $requiredClassification."
    }

    switch ($Purpose) {
        'Development' {
            $allowedFrom = ConvertTo-GoldMResearchDate -Value $policy.development.from -FieldName 'policy.development.from'
            $allowedTo = ConvertTo-GoldMResearchDate -Value $policy.development.to -FieldName 'policy.development.to'
            if ($from -lt $allowedFrom -or $to -gt $allowedTo) {
                throw "$Label is labeled Development but falls outside [$($policy.development.from), $($policy.development.to))."
            }
        }
        'Validation' {
            $allowedFrom = ConvertTo-GoldMResearchDate -Value $policy.validation.from -FieldName 'policy.validation.from'
            $allowedTo = ConvertTo-GoldMResearchDate -Value $policy.validation.to -FieldName 'policy.validation.to'
            if ($from -lt $allowedFrom -or $to -gt $allowedTo) {
                throw "$Label is labeled Validation but falls outside [$($policy.validation.from), $($policy.validation.to))."
            }
        }
        'BlindOos' {
            $firstUnexposedDate = ConvertTo-GoldMResearchDate -Value $policy.known_exposure.to -FieldName 'policy.known_exposure.to'
            if ($from -lt $firstUnexposedDate) {
                throw "$Label is labeled BlindOos but starts before $($policy.known_exposure.to). Earlier data is already exposed and may only be used diagnostically."
            }
        }
        'Diagnostic' {
            $allowedFrom = ConvertTo-GoldMResearchDate -Value $policy.known_exposure.from -FieldName 'policy.known_exposure.from'
            $allowedTo = ConvertTo-GoldMResearchDate -Value $policy.known_exposure.to -FieldName 'policy.known_exposure.to'
            if ($from -lt $allowedFrom -or $to -gt $allowedTo) {
                throw "$Label is labeled Diagnostic but falls outside known-exposure [$($policy.known_exposure.from), $($policy.known_exposure.to))."
            }
        }
    }
}
