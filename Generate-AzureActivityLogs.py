# ============================================================
# Azure Activity Log Generator and Validator
# Generates approximately 20 Activity Log records per run
# Exports events to CSV
# Uses only the dedicated test resource group
# ============================================================

$ErrorActionPreference = "Stop"

# ---------------- CONFIGURATION ----------------

$SubscriptionId   = "17654be6-a05c-4586-a5d9-e86cee340a80"
$ResourceGroupName = "ActivityLog-Test-RG"
$TagName           = "Validation"
$UpdatesToGenerate = 10

$OutputDirectory = Join-Path $env:USERPROFILE "Desktop\AzureActivityValidation"

$RunId = Get-Date -Format "yyyyMMdd_HHmmss"
$CsvPath = Join-Path $OutputDirectory "AzureActivityLogs_$RunId.csv"

New-Item -ItemType Directory -Path $OutputDirectory -Force |
    Out-Null

# ---------------- HELPER FUNCTION ----------------

function Get-EventText {
    param([object]$Value)

    if ($null -eq $Value) {
        return ""
    }

    # Current output may contain a plain string
    if ($Value -is [string]) {
        return $Value
    }

    # Also support versions that return an object
    foreach ($PropertyName in @("LocalizedValue", "Value")) {
        $Property = $Value.PSObject.Properties[$PropertyName]

        if ($null -ne $Property -and $Property.Value) {
            return [string]$Property.Value
        }
    }

    return [string]$Value
}

# ---------------- LOAD MODULES ----------------

foreach ($ModuleName in @("Az.Accounts", "Az.Resources", "Az.Monitor")) {

    if (-not (Get-Module -ListAvailable -Name $ModuleName)) {
        throw "Required module '$ModuleName' is missing. Install it before running this script."
    }

    Import-Module $ModuleName -ErrorAction Stop
}

# ---------------- AZURE LOGIN ----------------

$Context = Get-AzContext -ErrorAction SilentlyContinue

if ($null -eq $Context -or $null -eq $Context.Account) {
    Connect-AzAccount -ErrorAction Stop | Out-Null
}

Set-AzContext -SubscriptionId $SubscriptionId -ErrorAction Stop |
    Out-Null

Write-Host ""
Write-Host "Azure authentication successful." -ForegroundColor Green
Write-Host "Subscription: $SubscriptionId"
Write-Host "Test Resource Group: $ResourceGroupName"
Write-Host "Run ID: $RunId"
Write-Host ""

# ---------------- VERIFY TEST RESOURCE GROUP ----------------

$RG = Get-AzResourceGroup `
    -Name $ResourceGroupName `
    -ErrorAction Stop

$ResourceId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName"

# Save the original value of the Validation tag
$OriginalTagExists = $false
$OriginalTagValue = $null

if ($null -ne $RG.Tags -and $RG.Tags.ContainsKey($TagName)) {
    $OriginalTagExists = $true
    $OriginalTagValue = $RG.Tags[$TagName]
}

$TagChanged = $false
$LastTemporaryTagValue = $null

# Capture the start time immediately before generating events.
# Azure Activity Log event timestamps are represented in UTC.
$RunStartLocal = Get-Date
$RunStartUtc = $RunStartLocal.ToUniversalTime()

# ---------------- GENERATE EVENTS ----------------

try {
    for ($i = 1; $i -le $UpdatesToGenerate; $i++) {

        $LastTemporaryTagValue = "Validation-$RunId-$i"

        $TagPatch = @{}
        $TagPatch[$TagName] = $LastTemporaryTagValue

        # Mark before the request so restoration is attempted
        # even if Azure applies a request but the client errors.
        $TagChanged = $true

        Update-AzTag `
            -ResourceId $ResourceId `
            -Tag $TagPatch `
            -Operation Merge `
            -ErrorAction Stop |
            Out-Null

        Write-Host "Tag update $i/$UpdatesToGenerate completed." `
            -ForegroundColor Green

        Start-Sleep -Seconds 2
    }
}
finally {
    # ---------------- RESTORE ORIGINAL TAG STATE ----------------

    if ($TagChanged) {
        try {
            if ($OriginalTagExists) {

                $RestoreTag = @{}
                $RestoreTag[$TagName] = $OriginalTagValue

                Update-AzTag `
                    -ResourceId $ResourceId `
                    -Tag $RestoreTag `
                    -Operation Merge `
                    -ErrorAction Stop |
                    Out-Null

                Write-Host "Original Validation tag restored." `
                    -ForegroundColor Green
            }
            else {
                $DeleteTag = @{}
                $DeleteTag[$TagName] = $LastTemporaryTagValue

                Update-AzTag `
                    -ResourceId $ResourceId `
                    -Tag $DeleteTag `
                    -Operation Delete `
                    -ErrorAction Stop |
                    Out-Null

                Write-Host "Temporary Validation tag removed." `
                    -ForegroundColor Green
            }
        }
        catch {
            Write-Warning "Tag restoration failed. Check the Validation tag manually."
            Write-Warning $_.Exception.Message
        }
    }
}

# ---------------- RETRIEVE ACTIVITY LOGS ----------------

Write-Host ""
Write-Host "Waiting for Azure Activity Logs to appear..." `
    -ForegroundColor Cyan

Start-Sleep -Seconds 20

$RunEvents = @()
$AllLogs = @()

# Use a small buffer for the query, then filter by the run's
# UTC start time. Retry while Azure publishes the events.
$QueryStartTime = $RunStartLocal.AddMinutes(-1)

for ($Attempt = 1; $Attempt -le 12; $Attempt++)
 {

    $AllLogs = @(
        Get-AzActivityLog `
            -ResourceGroupName $ResourceGroupName `
            -StartTime $QueryStartTime `
            -EndTime (Get-Date) `
            -MaxRecord 1000
    )

    $RunEvents = @(
        foreach ($Event in $AllLogs) {

            if ($null -eq $Event.EventTimestamp) {
                continue
            }

            # Treat the timestamp clock value as UTC.
            # This avoids comparing UTC event times with local time.
            $EventTimeUtc = [DateTime]::SpecifyKind(
                [DateTime]$Event.EventTimestamp,
                [DateTimeKind]::Utc
            )

            if ($EventTimeUtc -ge $RunStartUtc.AddSeconds(-5)) {
                $Event
            }
        }
    )

       Write-Host "Attempt ${Attempt}: retrieved $($RunEvents.Count) events for this run."
    if ($RunEvents.Count -ge ($UpdatesToGenerate * 2)) {
        break
    }

    if ($Attempt -lt 12) {
        Start-Sleep -Seconds 15
    }
}

# Fallback: keep the recent query results for troubleshooting
# if the timestamp filter did not match the returned timestamps.
if ($RunEvents.Count -eq 0 -and $AllLogs.Count -gt 0) {
    Write-Warning "No timestamps matched the run window. Exporting the recent query results for inspection."
    $RunEvents = @($AllLogs)
}

# ---------------- PREPARE CSV ----------------

$Rows = @(
    foreach ($Event in $RunEvents) {

        $Operation = Get-EventText $Event.OperationName
        $Status = Get-EventText $Event.Status

        $TimestampUtc = ""
        if ($null -ne $Event.EventTimestamp) {
            $TimestampUtc = [DateTime]::SpecifyKind(
                [DateTime]$Event.EventTimestamp,
                [DateTimeKind]::Utc
            ).ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
        }

        [PSCustomObject]@{
            EventTimestampUtc = $TimestampUtc
            Operation         = $Operation
            Status            = $Status
            Caller            = $Event.Caller
            ResourceGroupName = $Event.ResourceGroupName
            ResourceId        = $Event.ResourceId
            CorrelationId     = $Event.CorrelationId
        }
    }
)

# ---------------- EXPORT AND VALIDATE ----------------

if ($Rows.Count -gt 0) {

    $Rows |
        Export-Csv `
            -Path $CsvPath `
            -NoTypeInformation `
            -Encoding UTF8

    $TagWriteEvents = @(
        $Rows | Where-Object {
            $_.Operation -match "(?i)(write tags|tags/write)"
        }
    )

    $StartedCount = @(
        $TagWriteEvents | Where-Object {
            $_.Status -match "^(Start|Started)$"
        }
    ).Count

    $SucceededCount = @(
        $TagWriteEvents | Where-Object {
            $_.Status -match "^(Success|Succeeded)$"
        }
    ).Count

    Write-Host ""
    Write-Host "========== VALIDATION SUMMARY ==========" `
        -ForegroundColor Cyan

    Write-Host "Total records exported : $($Rows.Count)"
    Write-Host "Tag-write Started      : $StartedCount"
    Write-Host "Tag-write Succeeded    : $SucceededCount"
    Write-Host "CSV file               : $CsvPath"

    if ($SucceededCount -ge $UpdatesToGenerate) {
        Write-Host "Validation: PASSED" -ForegroundColor Green
    }
    else {
        Write-Warning "Expected tag-write successes were not all visible yet. Review the CSV and Azure Activity Log."
    }

    Write-Host ""
    $Rows |
        Select-Object EventTimestampUtc, Operation, Status,
            ResourceGroupName |
        Format-Table -AutoSize
}
else {
    Write-Warning "No Activity Log records were returned. Review the Azure Portal Activity Log and retry later."
}

Write-Host ""
Write-Host "Run completed." -ForegroundColor Cyan
