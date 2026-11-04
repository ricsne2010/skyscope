// "Install SkyScope.exe" and "Uninstall SkyScope.exe": open the installer's or the uninstaller's window
// without a console window, with their own icons (which .bat files can't have). One program, built twice by
// installer\windows\build_launcher.ps1 with Windows' own C# compiler; what it does goes by its name:
//   Install...    runs installer\windows\install.ps1 beside it (the downloaded folder)
//   Uninstall...  runs uninstall.ps1 beside it (the install folder), or, from the downloaded folder, the one in
//                 the folder Windows has on record for the app (Settings > Apps); its arguments (-Quiet) go along
// Designed and Created by Project Moon Pi.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("SkyScope setup")]
[assembly: AssemblyDescription("Installs or uninstalls SkyScope")]
[assembly: AssemblyProduct("SkyScope")]
[assembly: AssemblyCompany("Project Moon Pi")]
[assembly: AssemblyCopyright("Designed and Created by Project Moon Pi")]
[assembly: AssemblyVersion("1.1.0.0")]

static class Launcher
{
    const string App = "SkyScope";
    const string Product = "SkyScope";
    const string Key = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\ProjectMoonPi.SkyScope";

    [STAThread]
    static int Main(string[] args)
    {
        string here = AppDomain.CurrentDomain.BaseDirectory;
        bool uninstall = Path.GetFileName(Application.ExecutablePath).StartsWith("Uninstall", StringComparison.OrdinalIgnoreCase);
        string script;
        if (uninstall)
        {
            script = Path.Combine(here, "uninstall.ps1");
            if (!File.Exists(script))
            {
                string where = null;
                using (var k = Registry.CurrentUser.OpenSubKey(Key)) { if (k != null) where = k.GetValue("InstallLocation") as string; }
                script = where == null ? null : Path.Combine(where, "uninstall.ps1");
                if (script == null || !File.Exists(script))
                {
                    MessageBox.Show(Product + " isn't installed on this PC.", "Uninstall " + Product, MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return 1;
                }
            }
        }
        else
        {
            script = Path.Combine(here, @"installer\windows\install.ps1");
            if (!File.Exists(script))
            {
                // run straight from the zip: Windows copies only this file out
                MessageBox.Show("Extract the zip first: right-click it, choose Extract All, then open Install " + App +
                                " in the extracted folder.", "Install " + Product, MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 1;
            }
        }
        var start = new ProcessStartInfo(
            Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe"),
            "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\" " + string.Join(" ", args))
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(script)
        };
        var p = Process.Start(start);
        // The window takes a few seconds to open. If PowerShell stops before it does, say so with the end of the
        // installer's log: a hidden PowerShell has no other way to tell anyone, and the click would seem to do nothing.
        if (p.WaitForExit(30000) && p.ExitCode != 0 && !WindowOpened())
        {
            string what = uninstall ? "The uninstaller" : "The installer";
            MessageBox.Show(what + " stopped before its window opened (exit code " + p.ExitCode + ")." +
                            (Tail() == "" ? "" : "\n\n" + Tail()) + "\n\nThe details are in " + LogFile +
                            ". Please send that file to Project Moon Pi.", (uninstall ? "Uninstall " : "Install ") + Product,
                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
        return 0;
    }

    static readonly string LogFile = Path.Combine(Path.GetTempPath(), App + " install.log");

    // the log's lines since the installer last started ("== <date> ... installer")
    static string[] LastRun()
    {
        try
        {
            var lines = File.ReadAllLines(LogFile);
            int from = Array.FindLastIndex(lines, l => l.StartsWith("== "));
            return from < 0 ? lines : lines.Skip(from).ToArray();
        }
        catch { return new string[0]; }
    }

    static bool WindowOpened() { return LastRun().Any(l => l.EndsWith(" window shown")); }

    static string Tail()
    {
        var run = LastRun();
        return string.Join("\n", run.Skip(Math.Max(0, run.Length - 6)));
    }
}
