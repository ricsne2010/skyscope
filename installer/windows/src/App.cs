// SkyScope's own details for the Windows programs (Install SkyScope.exe, Uninstall SkyScope.exe, SkyScope.exe).
// Everything else in this folder is the same for Project Moon Pi's other apps; this file is what differs.
// Designed and Created by Project Moon Pi.
using System;
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
    public const string Name = "SkyScope";
    public const string Id = "ProjectMoonPi.SkyScope";                 // Settings > Apps, the stop signal
    public const string Url = "https://github.com/projectmoonpi/skyscope";
    public const int DefaultPort = 7700;
    public const string Tagline = "A live aircraft radar, in your web browser.";
    public const string FirewallRule = "SkyScope (phones and Satellites on your network)";
    public const string PhonesText = "Let phones, tablets and SkyScope Satellite displays on my Wi-Fi open it";
    public const string PhonesWho = "phones, tablets and SkyScope Satellite displays";
    public const string PhonesShort = "phones and Satellites";

    // Python: the oldest SkyScope runs on, and the one installed when there's none (python.org, for this user only;
    // the version SkyScope's packages were tested with: move it on, with its checksums, once a newer one is tried)
    public static readonly Version PythonMin = new Version(3, 10);
    public const string PyVersion = "3.15.2";
    public static readonly string[][] PyFiles = {        // the installer for each kind of PC, and its SHA-256
        new[] { "AMD64", "python-3.15.2-amd64.exe", "06e225a228191b0f4d1dcf6905fbb21bf9f6970d13a2ec63137ab9bee76f15aa" },
        new[] { "ARM64", "python-3.15.2-arm64.exe", "a3957667a6305f0fa4c5ce6c73def927ddcad36190b9e27eb4a04e1a9a153c93" },
        new[] { "x86", "python-3.15.2.exe", "a1040151c8af7a31dcfa3d4da2648040806dfe86050622166cbebc7747f23027" },
    };

    // what pip installs into SkyScope's own Python set-up: [packages, what the window says, required?]
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

    public static string Runner(string dir) { return Path.Combine(dir, "run.py"); }

    // the program's arguments: run.py passes them to skyscope.py
    public static string RunArgs(bool phones)
    {
        return "--tray" + (phones ? "" : " --host 127.0.0.1");
    }

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
