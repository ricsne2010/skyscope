// SkyScope.exe, in the install folder: starts and stops the app, and is the app's own process while it runs.
//   SkyScope.exe                 Start: starts it in the background if it isn't running, then opens it in the browser
//   SkyScope.exe --no-browser    Start without opening the browser (at sign-in, and by the installer)
//   SkyScope.exe --stop [--quiet]   Stop (--quiet: no message afterwards)
//   SkyScope.exe --uninstall     opens Uninstall <App>.exe beside it (the Start menu's Remove <App>)
//   SkyScope.exe --run           the app itself: runs its Python program hidden and stays while it runs, so Task
//                                Manager lists it under the app's own name and icon (Python's own files are never
//                                changed). Stopping it ends the venv's Python launcher, which takes Python with it.
// Designed and Created by Project Moon Pi.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;

static class Runner
{
    static string StopSignal { get { return "Local\\" + App.Id + ".Stop"; } }

    public static string PythonW(string dir) { return Path.Combine(dir, @"venv\Scripts\pythonw.exe"); }

    // --run: the app itself
    public static int Run(string dir)
    {
        bool phones = App.InstalledFlag(dir, "phones", true);
        var args = Proc.Quote(App.Runner(dir)) + " " + App.RunArgs(phones);
        var si = new ProcessStartInfo(PythonW(dir), args) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = dir };
        si.EnvironmentVariables["PYGAME_HIDE_SUPPORT_PROMPT"] = "1";
        Process p;
        try { p = Process.Start(si); }
        catch (Exception e)
        {
            File.AppendAllText(Path.Combine(dir, App.Name.ToLowerInvariant() + ".log"), DateTime.Now + " couldn't start Python: " + e.Message + "\r\n");
            return 1;
        }
        try { File.WriteAllText(Path.Combine(dir, App.Name.ToLowerInvariant() + ".pid"), Process.GetCurrentProcess().Id.ToString()); } catch { }
        using (var stop = new EventWaitHandle(false, EventResetMode.ManualReset, StopSignal))
        using (var ended = new ManualResetEvent(false) { SafeWaitHandle = new Microsoft.Win32.SafeHandles.SafeWaitHandle(p.Handle, false) })
        {
            int which = WaitHandle.WaitAny(new WaitHandle[] { ended, stop });
            if (which == 1)
            {
                // asked to stop (Stop found it wasn't answering its shutdown request): end Python
                try { p.Kill(); } catch { }
                return 0;
            }
        }
        return p.ExitCode;
    }

    // Start (and --no-browser)
    public static int Start(string dir, bool browser)
    {
        int port = App.InstalledPort(dir);
        string url = "http://127.0.0.1:" + port + "/radar";
        bool installing = Environment.GetEnvironmentVariable("SS_INSTALLING") == "1";
        if (Web.Up(port))
        {
            if (browser) { using (Note("SkyScope is already running. Opening the radar...")) { Proc.Open(url); Sleep(3000); } }
            return 0;
        }
        var host = Process.Start(new ProcessStartInfo(App.Exe, "--run") { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = dir });
        using (installing ? null : Note("Starting " + App.Name + "..."))
        {
            for (int i = 0; i < 180 && !host.HasExited; i++)
            {
                if (Web.Up(port, 1000)) break;
                Sleep(500);
            }
        }
        if (!Web.Up(port))
        {
            MessageBox.Show(App.Name + " didn't start. Its messages are in " + Path.Combine(dir, App.Name.ToLowerInvariant() + ".log"),
                            App.Name, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        if (browser) Proc.Open(url);
        return 0;
    }

    // Stop: the app's own shutdown request first (its icon by the clock then goes by itself), then firmer if needed.
    // Also stops an install from before SkyScope.exe (any program running from the install folder).
    public static int Stop(string dir, bool quiet)
    {
        int port = App.InstalledPort(dir);
        bool wasUp = Web.Up(port, 1500);
        if (wasUp && Web.AskToStop(port))
        {
            for (int i = 0; i < 40 && Web.Up(port, 500); i++) Sleep(250);
        }
        // the host: told to stop, then ended if it hasn't
        try { using (var e = EventWaitHandle.OpenExisting(StopSignal)) e.Set(); } catch { }
        var host = HostProcess(dir);
        if (host != null && !host.WaitForExit(5000)) { try { host.Kill(); } catch { } }
        // the icon by the clock leaves by itself within a few seconds of the app (ending it by force would leave a
        // dead icon there until the mouse passes over it), so only what's still running after that is ended
        for (int i = 0; i < 16 && RunningFrom(dir).Any(); i++) Sleep(500);
        foreach (var p in RunningFrom(dir)) { try { p.Kill(); } catch { } }
        bool still = true;
        for (int i = 0; i < 20; i++) { if (!Web.Up(port, 500)) { still = false; break; } Sleep(250); }
        Files.TryDelete(Path.Combine(dir, App.Name.ToLowerInvariant() + ".pid"));
        if (!quiet)
        {
            if (still) MessageBox.Show(App.Name + " is still running: something else may be using port " + port + ".", App.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            else using (Note(wasUp ? App.Name + " has stopped." : App.Name + " wasn't running.")) Sleep(3500);
        }
        return still ? 1 : 0;
    }

    static Process HostProcess(string dir)
    {
        try
        {
            int id = int.Parse(File.ReadAllText(Path.Combine(dir, App.Name.ToLowerInvariant() + ".pid")).Trim());
            var p = Process.GetProcessById(id);
            string at = Proc.PathOf(p);
            return at != null && at.StartsWith(dir + "\\", StringComparison.OrdinalIgnoreCase) ? p : null;
        }
        catch { return null; }
    }

    // programs running from the install folder (but not this one)
    static Process[] RunningFrom(string dir)
    {
        int me = Process.GetCurrentProcess().Id;
        return Process.GetProcesses().Where(p =>
        {
            if (p.Id == me) return false;
            string at = Proc.PathOf(p);
            return at != null && at.StartsWith(dir + "\\", StringComparison.OrdinalIgnoreCase)
                   && !Path.GetFileName(at).StartsWith("Uninstall", StringComparison.OrdinalIgnoreCase)
                   && !Path.GetFileName(at).StartsWith("Install", StringComparison.OrdinalIgnoreCase);
        }).ToArray();
    }

    // a notice by the clock (gone when disposed)
    static IDisposable Note(string text)
    {
        var icon = new NotifyIcon { Visible = true, Text = App.Name };
        try { icon.Icon = System.Drawing.Icon.ExtractAssociatedIcon(App.Exe); } catch { icon.Icon = System.Drawing.SystemIcons.Information; }
        icon.ShowBalloonTip(5000, App.Name, text, ToolTipIcon.Info);
        return icon;
    }

    static void Sleep(int ms)
    {
        for (int t = 0; t < ms; t += 50) { Application.DoEvents(); Thread.Sleep(50); }
    }
}
