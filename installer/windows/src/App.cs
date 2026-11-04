// SkyScope's own details for the Windows programs (Install SkyScope.exe, Uninstall SkyScope.exe, SkyScope.exe).
// App.cs, Install.cs and Uninstall.cs are the app's own; Common.cs, Ui.cs, Runner.cs, Firewall.cs, Shortcuts.cs and
// Program.cs are the same in every Project Moon Pi app (Train Tracker, SkyScope, Aviator Trail): change them in all.
// Designed and Created by Project Moon Pi.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

[assembly: AssemblyTitle("SkyScope")]
[assembly: AssemblyDescription("SkyScope, a live aircraft radar")]
[assembly: AssemblyProduct("SkyScope")]
[assembly: AssemblyCompany("Project Moon Pi")]
[assembly: AssemblyCopyright("Designed and Created by Project Moon Pi")]
[assembly: AssemblyVersion("2.0.0.0")]

static partial class App
{
    public const string Name = "SkyScope";                 // folders, shortcuts, programs (<Name>.exe), the log
    public const string Display = "SkyScope";              // the window's header, Settings > Apps
    public const string Id = "ProjectMoonPi.SkyScope";     // Settings > Apps, the stop signal
    public const string Slug = "skyscope";                 // <slug>.log and <slug>.pid in the install folder
    public const string Url = "https://github.com/projectmoonpi/skyscope";
    public const string InfoFile = "install.json";         // what the installer wrote: port, choices, version
    // where earlier versions installed it (worked out when asked: a static field here can't rely on Common.cs's)
    public static string[] OldDirs { get { return new[] { Path.Combine(LocalAppData, "SkyScope") }; } }   // (before 1.6)

    // its web pages: where Start opens, and the address that says it's running
    public const int DefaultPort = 7700;
    public const string OpenPath = "/radar";
    public const string ProbePath = "/radar";
    public const string PageName = "the radar";
    public static readonly string StopHeader = "X-SkyScope";         // its /api/shutdown request (null: it has none)
    public const int StartSeconds = 90;
    public const string StartingNote = "Starting SkyScope...";

    // its shortcuts in the Start menu (and on the Desktop if wanted): name, <App>.exe's arguments, icon, description
    public static readonly string[][] Links = {
        new[] { "Start SkyScope", "", "start", "Start SkyScope and open the radar" },
        new[] { "Stop SkyScope", "--stop", "stop", "Stop SkyScope" },
    };

    // the Python that runs it: its own Python set-up's (venv), without a console window
    public static string PythonW(string dir) { return Path.Combine(dir, @"venv\Scripts\pythonw.exe"); }

    // the icons in the install folder (copied from tools\launcher)
    public static string Icon(string kind)                 // "app", "start", "stop", "uninstall"
    {
        return kind == "app" ? "skyscope.ico" : "skyscope-" + kind + ".ico";
    }

    // Python: the oldest it runs on, and the one installed when there's none (python.org, for this user only; the
    // version its packages were tested with: move it on, with its checksums, once a newer one is tried)
    public static readonly Version PythonMin = new Version(3, 10);
    public const string PyVersion = "3.15.2";
    public const string PySize = "about 36 MB";
    public static readonly string[][] PyFiles = {        // the installer for each kind of PC, and its SHA-256
        new[] { "AMD64", "python-3.15.2-amd64.exe", "06e225a228191b0f4d1dcf6905fbb21bf9f6970d13a2ec63137ab9bee76f15aa" },
        new[] { "ARM64", "python-3.15.2-arm64.exe", "a3957667a6305f0fa4c5ce6c73def927ddcad36190b9e27eb4a04e1a9a153c93" },
        new[] { "x86", "python-3.15.2.exe", "a1040151c8af7a31dcfa3d4da2648040806dfe86050622166cbebc7747f23027" },
    };

    // phones (and Satellites) on the home network: the firewall rule and what the pages say about it
    public const string FirewallRule = "SkyScope (phones and Satellites on your network)";
    public const string PhonesText = "Let phones, tablets and SkyScope Satellite displays on my Wi-Fi open it";
    public const string PhonesWho = "phones, tablets and SkyScope Satellite displays";
    public const string PhonesShort = "phones and Satellites";

    // the Python program, run hidden by SkyScope.exe --run: venv\Scripts\pythonw.exe <these arguments>
    public static string RunArgs(string dir)
    {
        bool phones = InstalledFlag(dir, "phones", true);
        return Proc.Quote(Path.Combine(dir, "run.py")) + " --tray" + (phones ? "" : " --host 127.0.0.1");
    }

    // ---- SkyScope's own, used by its Install.cs and Uninstall.cs

    // what pip installs into its own Python set-up: [packages, what the window says, required?, hint]
    public static readonly string[][] Packages = {
        new[] { "pygame-ce", "Installing what SkyScope runs on...", "yes", "Downloading pygame-ce; about a minute." },
        new[] { "pystray pillow", "Installing the icon by the clock...", "no", "" },   // without them: no icon by the clock
    };

    // the program's files, copied from the installer's folder (filecheck.py sync compares them)
    public static readonly string[] ProgramItems = { "*.py", "web", "data", "docs", "README.md", "LICENSE" };
    // kept through updates and repairs (and moved along when the install folder changes)
    public static readonly string[] Keep = { "settings.json", "flightaware_usage.json", "logos_cache" };

    // the FlightAware key: kept outside the program's folder when an uninstall is asked to keep it
    public static readonly string KeptKey = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                                         @"Project Moon Pi\SkyScope FlightAware key.json");

    // the web port: settings.json's web_port, else the default
    public static int PortOf(string dir)
    {
        var s = Json.Read(Path.Combine(dir, "settings.json"));
        object p;
        if (s != null && s.TryGetValue("web_port", out p))
        {
            try { int n = Convert.ToInt32(p); if (n > 0) return n; } catch { }
        }
        return DefaultPort;
    }
}
