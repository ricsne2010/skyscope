# The installer's and uninstaller's window: the Project Moon Pi logo and the app's name across the top, then a page
# below it (choices, a progress bar, or done). Dot-source it, then:
#   UI-Open 'Install SkyScope' <logo.png> <icon.ico> 'SkyScope'   (window title, logo, icon, the name in the header)
#   UI-Choices 'text' @(@{text = '...'; checked = $true}, ...) 'Install'  -> the boxes' states, or $null on Cancel
#     -Folder <default path> -FolderCheck { param($path) <error text, or nothing if it's fine> }: an "Install in"
#     box with Browse...; the chosen folder is then in $UI_Folder
#     -Options @('Update to 1.2', 'Repair', ...) -Selected 0: one choice of several (round buttons); the chosen one's
#     number is then in $UI_Option
#   UI-Progress 'text' <percent>             moves the bar smoothly towards <percent> and says what's happening
#   UI-Wait <process> <percent>               keeps the window alive while a program runs, the bar creeping on
#   UI-Done 'text' 'Finish' @(@{text=...})    the last page; returns the boxes' states when closed
#   UI-Error 'text'
# With $UI_Unattended set, nothing waits for a click (the pages flash by). Designed and Created by Project Moon Pi.
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -Namespace PMP -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][PMP.Dpi]::SetProcessDPIAware()          # sharp text on scaled displays
[System.Windows.Forms.Application]::EnableVisualStyles()

$script:UI = @{}

function UI-Open($title, $logo, $icon, $appName) {
    $f = New-Object System.Windows.Forms.Form
    $f.Text = $title
    $f.AutoScaleDimensions = New-Object System.Drawing.SizeF(96, 96)
    $f.AutoScaleMode = 'Dpi'
    $f.ClientSize = New-Object System.Drawing.Size(560, 540)
    $f.StartPosition = 'CenterScreen'
    $f.FormBorderStyle = 'FixedDialog'
    $f.MaximizeBox = $false
    $f.BackColor = [System.Drawing.Color]::White
    $f.Font = New-Object System.Drawing.Font('Segoe UI', 9.75)
    # (the logo and icon are read into memory, so the uninstaller can delete their files)
    if ($icon -and (Test-Path $icon)) { $f.Icon = New-Object System.Drawing.Icon (New-Object IO.MemoryStream (, [IO.File]::ReadAllBytes($icon))) }

    # header: logo, name and credit on night blue
    $head = New-Object System.Windows.Forms.Panel -Property @{ Dock = 'Top'; Height = 104; BackColor = [System.Drawing.Color]::FromArgb(10, 22, 46) }
    if ($logo -and (Test-Path $logo)) {
        $pic = New-Object System.Windows.Forms.PictureBox -Property @{ Left = 20; Top = 12; Width = 80; Height = 80; SizeMode = 'Zoom' }
        $pic.Image = [System.Drawing.Image]::FromStream((New-Object IO.MemoryStream (, [IO.File]::ReadAllBytes($logo))))
        $head.Controls.Add($pic)
    }
    $name = New-Object System.Windows.Forms.Label -Property @{ Left = 116; Top = 24; Width = 420; Height = 34; Text = $appName
        ForeColor = [System.Drawing.Color]::White; Font = (New-Object System.Drawing.Font('Segoe UI Semibold', 17)) }
    $credit = New-Object System.Windows.Forms.Label -Property @{ Left = 118; Top = 60; Width = 420; Height = 22
        Text = 'Designed and Created by Project Moon Pi'; ForeColor = [System.Drawing.Color]::FromArgb(170, 185, 210) }
    $head.Controls.AddRange(@($name, $credit))

    # page: a heading, its text, then whatever the page needs; buttons at the bottom right
    $body = New-Object System.Windows.Forms.Panel -Property @{ Dock = 'Fill'; Padding = (New-Object System.Windows.Forms.Padding(24, 18, 24, 0)) }
    $text = New-Object System.Windows.Forms.Label -Property @{ Left = 24; Top = 18; Width = 512; Height = 96 }
    $bar = New-Object System.Windows.Forms.ProgressBar -Property @{ Left = 24; Top = 120; Width = 512; Height = 20; Style = 'Continuous'; Maximum = 1000; Visible = $false }
    $detail = New-Object System.Windows.Forms.Label -Property @{ Left = 24; Top = 148; Width = 512; Height = 40; Visible = $false
        ForeColor = [System.Drawing.Color]::FromArgb(100, 100, 110) }
    $ok = New-Object System.Windows.Forms.Button -Property @{ Width = 104; Height = 32; Left = 432; Top = 380; Visible = $false }
    $cancel = New-Object System.Windows.Forms.Button -Property @{ Width = 104; Height = 32; Left = 316; Top = 380; Text = 'Cancel'; Visible = $false }
    $body.Controls.AddRange(@($text, $bar, $detail, $ok, $cancel))
    $f.Controls.AddRange(@($body, $head))

    $script:UI = @{ Form = $f; Text = $text; Bar = $bar; Detail = $detail; Ok = $ok; Cancel = $cancel; Body = $body
                    Boxes = @(); Extra = @(); Clicked = $null; Target = 0; Closed = $false }
    $ok.Add_Click({ $script:UI.Clicked = 'ok' })
    $cancel.Add_Click({ $script:UI.Clicked = 'cancel' })
    $f.Add_FormClosing({
        # the window's X: as Cancel while choosing; ignored while working
        if ($script:UI.Ok.Visible -or $script:UI.Cancel.Visible) { $script:UI.Clicked = 'cancel' } elseif (-not $script:UI.Closed) { $_.Cancel = $true }
    })
    # the bar glides towards its target rather than jumping
    $timer = New-Object System.Windows.Forms.Timer -Property @{ Interval = 15 }
    $timer.Add_Tick({
        $b = $script:UI.Bar
        if ($b.Value -lt $script:UI.Target) { $b.Value = [Math]::Min($script:UI.Target, $b.Value + [Math]::Max(1, [int](($script:UI.Target - $b.Value) / 12))) }
    })
    $timer.Start()
    $script:UI.Timer = $timer
    $f.Show()
    UI-Pump
}

function UI-Pump { [System.Windows.Forms.Application]::DoEvents() }

function UI-Clear {
    foreach ($b in $script:UI.Boxes + $script:UI.Extra) { $script:UI.Body.Controls.Remove($b) }
    $script:UI.Boxes = @(); $script:UI.Extra = @()
    $script:UI.Bar.Visible = $false; $script:UI.Detail.Visible = $false
    $script:UI.Ok.Visible = $false; $script:UI.Cancel.Visible = $false
    $script:UI.Clicked = $null
}

function UI-AddBoxes($boxes, $top) {
    foreach ($spec in $boxes) {
        $c = New-Object System.Windows.Forms.CheckBox -Property @{ Left = 26; Top = $top; Width = 510; Height = 26; Text = $spec.text; Checked = [bool]$spec.checked }
        $script:UI.Body.Controls.Add($c)
        $script:UI.Boxes += $c
        $top += 30
    }
}

function UI-WaitClick {
    $script:UI.Form.Activate()
    while (-not $script:UI.Clicked) { UI-Pump; Start-Sleep -Milliseconds 20 }
    return $script:UI.Clicked
}

function UI-Choices($text, $boxes, $okText, [switch]$NoCancel, $Folder = $null, [scriptblock]$FolderCheck = $null,
                    $Options = @(), $Selected = 0, $TextHeight = 106) {
    UI-Clear
    $script:UI.Text.Text = $text
    $script:UI.Text.Height = $TextHeight      # (taller for a page with more to say)
    $top = $TextHeight + 26
    $script:UI_Folder = $Folder
    $script:UI_Option = $Selected
    $radios = @()
    if ($Options.Count) {
        $script:UI.Text.Height = 86; $top = 110      # (a few lines saying what is installed, then the choices)
        # one of several: Install, Update, Repair, Reinstall from scratch...
        foreach ($o in $Options) {
            $r = New-Object System.Windows.Forms.RadioButton -Property @{ Left = 26; Top = $top; Width = 510; Height = 26; Text = $o; Checked = ($radios.Count -eq $Selected) }
            $radios += $r
            $top += 28
        }
        $script:UI.Extra += $radios
        $script:UI.Body.Controls.AddRange($radios)
        $top += 6
    }
    if ($Folder) {
        # where it goes: a box with the default, and Browse... to pick another
        $label = New-Object System.Windows.Forms.Label -Property @{ Left = 24; Top = ($top - 4); Width = 512; Height = 20; Text = 'Install in:' }
        $box = New-Object System.Windows.Forms.TextBox -Property @{ Left = 26; Top = ($top + 18); Width = 400; Text = $Folder }
        $browse = New-Object System.Windows.Forms.Button -Property @{ Left = 434; Top = ($top + 16); Width = 102; Height = 28; Text = 'Browse...' }
        $browse.Add_Click({
            $d = New-Object System.Windows.Forms.FolderBrowserDialog -Property @{ Description = 'Choose where to install it' }
            if ($d.ShowDialog($script:UI.Form) -eq 'OK') { $script:UI.FolderBox.Text = $d.SelectedPath }
        })
        $script:UI.FolderBox = $box
        $script:UI.Extra += @($label, $box, $browse)
        $script:UI.Body.Controls.AddRange(@($label, $box, $browse))
        $top += 58
    }
    UI-AddBoxes $boxes $top
    $script:UI.Ok.Text = $okText; $script:UI.Ok.Visible = $true
    $script:UI.Cancel.Visible = -not $NoCancel
    $script:UI.Form.AcceptButton = $script:UI.Ok
    # (the leading comma keeps an empty list a list: a page with no boxes still says OK, not $null = Cancel)
    if ($UI_Unattended) { return , @($script:UI.Boxes | ForEach-Object { $_.Checked }) }
    while ($true) {
        if ((UI-WaitClick) -ne 'ok') { return $null }
        for ($i = 0; $i -lt $radios.Count; $i++) { if ($radios[$i].Checked) { $script:UI_Option = $i } }
        if (-not $Folder) { break }
        $script:UI_Folder = $script:UI.FolderBox.Text.Trim()
        $problem = if ($FolderCheck) { & $FolderCheck $script:UI_Folder }
        if (-not $problem) { break }
        [void][System.Windows.Forms.MessageBox]::Show($script:UI.Form, $problem, $script:UI.Form.Text, 'OK', 'Warning')
        $script:UI.Clicked = $null
    }
    return , @($script:UI.Boxes | ForEach-Object { $_.Checked })
}

function UI-Progress($text, $percent, $detail = '') {
    if ($script:UI.Ok.Visible -or $script:UI.Boxes.Count) { UI-Clear }
    $script:UI.Text.Text = $text
    $script:UI.Text.Height = 30; $script:UI.Bar.Top = 58; $script:UI.Detail.Top = 86    # text, bar and hint together
    $script:UI.Bar.Visible = $true
    $script:UI.Detail.Text = $detail; $script:UI.Detail.Visible = [bool]$detail
    $script:UI.Target = [int]([Math]::Min(100, $percent) * 10)
    UI-Pump
}

function UI-Wait($process, $upTo, $seconds = 60) {
    # while a program runs: keep the window alive and creep the bar towards $upTo (never quite reaching it)
    $null = $process.Handle      # (Windows PowerShell only keeps the exit code if the handle was taken while it ran)
    $from = $script:UI.Target
    $goal = [int]($upTo * 10)
    $start = Get-Date
    while (-not $process.HasExited) {
        $t = ((Get-Date) - $start).TotalSeconds / $seconds
        $script:UI.Target = [int]($from + ($goal - $from) * (1 - [Math]::Exp(-2 * $t)) * 0.95)
        UI-Pump
        Start-Sleep -Milliseconds 30
    }
    $process.WaitForExit()
    $script:UI.Target = $goal
    UI-Pump
    return $process.ExitCode
}

function UI-Done($text, $okText, $boxes = @()) {
    UI-Clear
    $script:UI.Target = 1000; $script:UI.Bar.Value = 1000
    $script:UI.Text.Text = $text
    $script:UI.Text.Height = 236
    UI-AddBoxes $boxes 262
    $script:UI.Ok.Text = $okText; $script:UI.Ok.Visible = $true
    $script:UI.Form.AcceptButton = $script:UI.Ok
    if (-not $UI_Unattended) { $null = UI-WaitClick }
    $states = @($script:UI.Boxes | ForEach-Object { $_.Checked })
    UI-Close
    return , $states
}

function UI-Error($text) {
    if ($UI_Unattended) { UI-Close; return }
    UI-Clear
    $script:UI.Text.Text = $text
    $script:UI.Text.Height = 300
    $script:UI.Ok.Text = 'Close'; $script:UI.Ok.Visible = $true
    $null = UI-WaitClick
    UI-Close
}

function UI-Close {
    $script:UI.Closed = $true
    $script:UI.Timer.Stop()
    $script:UI.Form.Close()
    UI-Pump
}
