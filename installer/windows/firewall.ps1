# Let phones, tablets and SkyScope Satellite displays on your home network reach SkyScope (or stop letting them).
#   firewall.ps1 -Allow -Program <pythonw.exe>   makes sure phones can connect; prints Allowed / AllowedPublic / Declined
#   firewall.ps1                                  removes our rule
# Reading rules works without admin rights (netsh); changing them needs admin, so Windows asks once, and only
# when something actually needs changing. Designed and Created by Project Moon Pi.
param([switch]$Allow, [int]$Port = 7700, [string]$Program = '')
$name = 'SkyScope (phones and Satellites on your network)'

function Get-InboundRules {
    # every inbound rule as a hashtable of netsh's "Key: value" lines
    $rules = @(); $cur = $null
    foreach ($line in (netsh advfirewall firewall show rule name=all dir=in verbose)) {
        if ($line -match '^Rule Name:\s*(.*)$') { if ($cur) { $rules += $cur }; $cur = @{ 'Rule Name' = $Matches[1].Trim() } }
        elseif ($cur -and $line -match '^([^:]+):\s*(.*)$') { $cur[$Matches[1].Trim()] = $Matches[2].Trim() }
    }
    if ($cur) { $rules += $cur }
    return $rules
}

function Get-State {
    $rules = Get-InboundRules
    $ours = @($rules | Where-Object { $_['Rule Name'] -eq $name })
    $mine = @($rules | Where-Object { $Program -and $_['Program'] -and ($_['Program'] -eq $Program) -and $_['Enabled'] -eq 'Yes' })
    $allows = @($ours | Where-Object { $_['Enabled'] -eq 'Yes' }) + @($mine | Where-Object { $_['Action'] -eq 'Allow' -and $_['Protocol'] -match 'TCP|Any' })
    return @{
        Ours    = $ours.Count
        Blocks  = @($mine | Where-Object { $_['Action'] -eq 'Block' }).Count
        Home    = [bool]@($allows | Where-Object { $_['Profiles'] -match 'Private|Domain' }).Count
        Public  = [bool]@($allows | Where-Object { $_['Profiles'] -match 'Public' }).Count
    }
}

function Invoke-Admin($commands) {
    # run netsh commands with admin rights; $true if they ran
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrators')
    $script = ($commands -join "`n") + "`nexit 0"
    try {
        if ($admin) { Invoke-Expression ($commands -join "`n"); return $true }
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
        $p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList "-NoProfile -EncodedCommand $encoded"
        return ($p.ExitCode -eq 0)
    } catch {
        return $false    # the admin prompt was declined or isn't available
    }
}

$s = Get-State
if (-not $Allow) {
    if ($s.Ours) { $null = Invoke-Admin @("netsh advfirewall firewall delete rule name=`"$name`" | Out-Null") }
    return
}

# already fine: an allow rule for home networks, exactly one of ours (if any), and nothing blocking this Python
if ($s.Home -and $s.Ours -le 1 -and -not $s.Blocks) {
    if ($s.Public) { 'AllowedPublic' } else { 'Allowed' }
    return
}
$cmds = @("netsh advfirewall firewall delete rule name=`"$name`" | Out-Null",
          "netsh advfirewall firewall add rule name=`"$name`" dir=in action=allow protocol=TCP localport=$Port profile=private,domain | Out-Null")
if ($s.Blocks -and $Program) {
    # Windows adds a Block rule when its "allow this app?" notice is cancelled; a block always beats an allow
    # (netsh can't tell block rules from allow rules when deleting, so this one uses PowerShell, which can when admin)
    $cmds += "Get-NetFirewallApplicationFilter -Program '$Program' | Get-NetFirewallRule | Where-Object { `$_.Direction -eq 'Inbound' -and `$_.Action -eq 'Block' } | Remove-NetFirewallRule"
}
$null = Invoke-Admin $cmds
$s = Get-State
if (-not $s.Home -or $s.Blocks) { 'Declined' } elseif ($s.Public) { 'AllowedPublic' } else { 'Allowed' }
