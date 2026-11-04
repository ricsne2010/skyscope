// One program, built three times (build.sh / build.ps1) with its own name and icon; what it does goes by its name:
//   Install <App>.exe     the installer's window (installer\windows\..\..: the downloaded folder)
//   Uninstall <App>.exe   the uninstaller's window
//   <App>.exe             Start, Stop and the app's own process (Runner.cs)
// and, whatever its name, --firewall allow|remove <port> [program]: the firewall change, run with admin rights.
// No PowerShell anywhere: antivirus programs (Bitdefender's Advanced Threat Defense, in our tests) take a hidden
// PowerShell that downloads, compiles and asks for admin rights for malware, whatever the script does.
// Designed and Created by Project Moon Pi.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            if (args.Length >= 3 && args[0] == "--firewall") return Firewall.Change(args);
            string name = Path.GetFileNameWithoutExtension(App.Exe);
            if (name.StartsWith("Install", StringComparison.OrdinalIgnoreCase)) return Install.Begin();
            if (name.StartsWith("Uninstall", StringComparison.OrdinalIgnoreCase)) return Uninstall.Begin(args);

            string dir = App.Here;
            if (args.Contains("--run")) return Runner.Run(dir);
            if (args.Contains("--stop")) return Runner.Stop(dir, args.Contains("--quiet"));
            if (args.Contains("--uninstall"))
            {
                Process.Start(new ProcessStartInfo(Path.Combine(dir, "Uninstall " + App.Name + ".exe")) { UseShellExecute = false, WorkingDirectory = dir });
                return 0;
            }
            if (!File.Exists(Path.Combine(dir, "install.json")))
            {
                MessageBox.Show(App.Name + " isn't installed in " + dir + ". Run Install " + App.Name + " first.", App.Name);
                return 1;
            }
            return Runner.Start(dir, !args.Contains("--no-browser"));
        }
        catch (Exception e)
        {
            App.Log("ERROR: " + e);
            MessageBox.Show(e.Message + "\n\nThe details are in " + App.LogFile + ".", App.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }
}
