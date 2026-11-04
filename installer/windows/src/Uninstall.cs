// Uninstall <App>.exe: removes the app, its shortcuts and its settings, in a window. Python stays.
//   In the install folder (Settings > Apps, Remove <App>): it copies itself to a folder in %TEMP% and carries on from
//   there (--from <install folder>), as a program can't remove the folder it's running from.
//   Beside the installer (the downloaded folder): it removes the copy Windows has on record (Settings > Apps).
//   -Quiet (or SS_UNATTENDED=1): no window, no questions.
// Designed and Created by Project Moon Pi.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using Microsoft.Win32;

static class Uninstall
{
    public static int Begin(string[] args)
    {
        bool quiet = args.Any(a => a.Equals("-Quiet", StringComparison.OrdinalIgnoreCase) || a == "--quiet")
                     || Environment.GetEnvironmentVariable("SS_UNATTENDED") == "1";
        int at = Array.IndexOf(args, "--from");
        string dir = at >= 0 && at + 1 < args.Length ? args[at + 1] : null;
        if (dir == null)
        {
            if (App.IsInstalledIn(App.Here))
            {
                // in the install folder: carry on from a copy in %TEMP%
                string tmp = Path.Combine(Path.GetTempPath(), App.Name + " uninstall " + Process.GetCurrentProcess().Id);
                Directory.CreateDirectory(tmp);
                string copy = Path.Combine(tmp, Path.GetFileName(App.Exe));
                File.Copy(App.Exe, copy, true);
                var more = new List<string> { "--from", App.Here };
                if (quiet) more.Add("-Quiet");
                Process.Start(new ProcessStartInfo(copy, Proc.Join(more)) { UseShellExecute = false, WorkingDirectory = tmp });
                return 0;
            }
            dir = App.InstalledDir();
            if (dir == null)
            {
                if (!quiet) Ui.Say(App.Name + " isn't installed on this PC.");
                return 1;
            }
        }
        Ui.Unattended = quiet;
        App.LogHeader("uninstaller");
        try { return Steps(dir.TrimEnd('\\'), quiet); }
        catch (Exception e)
        {
            App.Log("ERROR: " + e);
            if (quiet) return 1;
            Ui.Error(App.Name + " wasn't fully removed.\n\n" + e.Message);
            return 1;
        }
    }

    static int Steps(string dir, bool quiet)
    {
        // a FlightAware key: asked about on its own (it's yours, from FlightAware's site; kept, it comes back next time)
        var fa = Json.Read(Path.Combine(dir, "settings.json"));
        string key = fa != null && fa.ContainsKey("flightaware_key") ? Convert.ToString(fa["flightaware_key"]) : "";
        bool dropKey = true;
        if (!quiet)
        {
            Ui.Open("Uninstall " + App.Name, Path.Combine(dir, "logo.png"), Path.Combine(dir, App.Icon("uninstall")), App.Name);
            var boxes = new List<Box>();
            if (key != "") boxes.Add(new Box("Also delete my FlightAware API key (ending " + key.Substring(Math.Max(0, key.Length - 4)) + ")", true));
            string text = "Remove " + App.Name + " from this PC?\n\nIt stops " + App.Name + " and removes the program, its shortcuts and its settings (location, filters). Python stays, for anything else that uses it.";
            if (key != "") text += "\n\nTo keep your FlightAware API key for next time, untick the box: installing " + App.Name + " again puts it back.";
            var answers = Ui.Choices(text, boxes, "Uninstall", false, null, null, key != "" ? 150 : 106);
            if (answers == null) { Ui.Close(); return 0; }
            if (key != "") dropKey = answers[0];
        }
        if (key != "" && !dropKey)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(App.KeptKey));
            Json.Write(App.KeptKey, new Dictionary<string, object> { { "flightaware_key", key },
                { "flightaware_daily_limit", fa.ContainsKey("flightaware_daily_limit") ? Convert.ToString(fa["flightaware_daily_limit"]) : "" } });
        }
        else if (key != "") Files.TryDelete(App.KeptKey);       // (one kept from an earlier uninstall goes too)

        Ui.Progress("Stopping " + App.Name + "...", 10);
        Runner.Stop(dir, true);
        int port = App.InstalledPort(dir);

        // close the port for phones and Satellites (Windows asks for permission only if there's a rule to remove)
        Ui.Progress("Closing the firewall for " + App.PhonesShort + "...", 50);
        Firewall.Remove(port, quiet);

        Ui.Progress("Removing the shortcuts...", 65);
        Shortcuts.RemoveAll();
        Registry.CurrentUser.DeleteSubKeyTree(App.UninstallKey, false);      // Settings > Apps

        Ui.Progress("Removing the program and its settings...", 90);
        Directory.SetCurrentDirectory(Path.GetTempPath());
        // (a program that has just been ended can hold its files a moment longer)
        for (int i = 0; i < 40 && Directory.Exists(dir); i++)
        {
            Files.TryDeleteDir(dir);
            if (Directory.Exists(dir)) Ui.Breathe(250);
        }
        // and the Project Moon Pi folder it was in, once it's empty (no other Project Moon Pi app left there)
        string parent = Path.GetDirectoryName(dir);
        try
        {
            if (Path.GetFileName(parent) == "Project Moon Pi" && !Directory.EnumerateFileSystemEntries(parent).Any()) Directory.Delete(parent);
        }
        catch { }
        bool left = Directory.Exists(dir);
        App.Log("removed " + dir + (left ? " (some files were in use)" : ""));
        if (!quiet)
        {
            string kept = key != "" && !dropKey ? "\n\nYour FlightAware API key is kept on this PC: installing " + App.Name + " again puts it back." : "";
            Ui.Done(App.Name + " has been removed." + kept + (left ? "\n\nA few files in " + dir + " were in use; they go when you restart the PC, or you can delete that folder." : ""), "Close");
        }
        return 0;
    }
}
