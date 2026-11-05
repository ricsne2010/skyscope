// Install <App>.exe: installs the app on this PC, in a window (run it again later to update, repair or reinstall
// from scratch; your settings are kept). It runs from the downloaded folder, beside the program's files.
//
// Installs the program in %LOCALAPPDATA%\Programs\Project Moon Pi\<App> (or a folder you choose), with <App>.exe and
// Uninstall <App>.exe in it; puts Start, Stop and Remove <App> in the Start menu, Start and Stop on the Desktop if you
// like, and lists it in Settings > Apps. Needs Python (App.PythonMin); if it isn't there, it installs Python from
// python.org for this user only (checked: the expected download, signed by the Python Software Foundation). What it
// does is logged in %TEMP%\<App> install.log. Designed and Created by Project Moon Pi.
//
// Unattended (tests): answer ahead with SS_PHONES=yes|no SS_AUTOSTART=yes|no SS_DESKTOP=yes|no SS_OPEN=no
// SS_PYTHON=yes|no SS_DIR=<folder> SS_MODE=update|repair|fresh; the window then needs no clicks.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using Microsoft.Win32;

class Py
{
    public string Exe; public string[] Pre;
    public Py(string exe, params string[] pre) { Exe = exe; Pre = pre; }
    public string[] With(params string[] args) { return Pre.Concat(args).ToArray(); }
}

static class Install
{
    static string Src;            // the downloaded folder (the program's files)
    static string AppDir;
    static string WasRunning;
    static int LastCode;
    static string Env(string name) { return Environment.GetEnvironmentVariable(name); }

    // a program run hidden, its output in the log, while the window keeps going
    static string Run(string exe, IEnumerable<string> args, string what, double upTo, double seconds = 60, params int[] ok)
    {
        var argv = args.ToList();
        App.Log(what + ": " + exe + " " + Proc.Join(argv));
        var output = new StringBuilder();
        Process p;
        try { p = Proc.StartHidden(exe, argv, AppDir != null && Directory.Exists(AppDir) ? AppDir : null, output); }
        catch (Exception e) { throw new Exception(what + " didn't work: " + e.Message); }
        int code = Ui.Wait(p, upTo, seconds);
        string text;
        lock (output) text = output.ToString();
        if (text.Trim().Length > 0) App.Log(text.Trim());
        LastCode = code;
        if (!(ok.Length == 0 ? new[] { 0 } : ok).Contains(code)) throw new Exception(what + " didn't work (exit code " + code + ").");
        return text;
    }

    static string LastLine(string text)
    {
        return text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).LastOrDefault() ?? "";
    }

    // ---- Python

    // the PATH as Windows has it now (a window opened before Python was installed still has the old one)
    static void FreshPath()
    {
        var parts = new[] { Environment.GetEnvironmentVariable("PATH"),
                            Environment.GetEnvironmentVariable("PATH", EnvironmentVariableTarget.User),
                            Environment.GetEnvironmentVariable("PATH", EnvironmentVariableTarget.Machine) };
        Environment.SetEnvironmentVariable("PATH", string.Join(";", parts.Where(p => !string.IsNullOrEmpty(p))));
    }

    // a new enough Python: the "py" launcher from python.org, python on the PATH, one Windows has on record as
    // installed, or python.org's usual folders
    static Py FindPython()
    {
        FreshPath();
        string check = "import sys; sys.exit(sys.version_info < (" + App.PythonMin.Major + ", " + App.PythonMin.Minor + "))";
        var found = new List<Py> { new Py("py", "-3"), new Py("python") };
        foreach (var hive in new[] { Registry.CurrentUser, Registry.LocalMachine })
            foreach (var key in new[] { @"Software\Python\PythonCore", @"Software\WOW6432Node\Python\PythonCore" })
                using (var k = hive.OpenSubKey(key))
                {
                    if (k == null) continue;
                    foreach (var v in k.GetSubKeyNames())
                        using (var ip = k.OpenSubKey(v + @"\InstallPath"))
                        {
                            var exe = ip == null ? null : ip.GetValue("ExecutablePath") as string;
                            if (!string.IsNullOrEmpty(exe) && File.Exists(exe)) found.Add(new Py(exe));
                        }
                }
        foreach (var root in new[] { Path.Combine(App.LocalAppData, @"Programs\Python"), Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles) })
        {
            try
            {
                foreach (var d in Directory.GetDirectories(root, "Python3*").OrderByDescending(d => int.TryParse(Regex.Replace(Path.GetFileName(d), @"\D", ""), out int n) ? n : 0))
                    if (File.Exists(Path.Combine(d, "python.exe"))) found.Add(new Py(Path.Combine(d, "python.exe")));
            }
            catch { }
        }
        foreach (var c in found)
            if (Proc.Quick(c.Exe, c.With("-c", check), 30) == 0) return c;     // (not the Microsoft Store's placeholder)
        return null;
    }

    static void InstallPython()
    {
        string arch = Env("PROCESSOR_ARCHITEW6432") ?? Env("PROCESSOR_ARCHITECTURE") ?? "x86";
        var want = App.PyFiles.FirstOrDefault(f => string.Equals(f[0], arch, StringComparison.OrdinalIgnoreCase))
                   ?? App.PyFiles.First(f => f[0] == "x86");
        string exe = Path.Combine(Path.GetTempPath(), want[1]);
        string url = "https://www.python.org/ftp/python/" + App.PyVersion + "/" + want[1];
        App.Log("downloading " + url);
        long have = 0, total = 0;
        Exception failed = null;
        bool finished = false;
        using (var wc = new WebClient())
        {
            wc.DownloadProgressChanged += (s, e) => { have = e.BytesReceived; total = e.TotalBytesToReceive; };
            wc.DownloadFileCompleted += (s, e) => { failed = e.Error; finished = true; };
            wc.DownloadFileAsync(new Uri(url), exe);
            while (!finished)
            {
                int pc = total > 0 ? (int)Math.Min(100, 100 * have / total) : 0;
                Ui.Progress("Downloading Python " + App.PyVersion + " from python.org...", 2 + 18 * pc / 100.0,
                            total > 0 ? pc + "% of " + Math.Round(total / 1048576.0) + " MB" : "");
                Ui.Breathe(60);
            }
        }
        if (failed != null)
        {
            App.Log("download: " + failed.Message);
            throw new Exception("Python couldn't be downloaded. Check the internet connection, then run the installer again.");
        }
        try
        {
            Ui.Progress("Checking the Python download...", 21);
            string hash;
            using (var f = File.OpenRead(exe)) hash = BitConverter.ToString(SHA256.Create().ComputeHash(f)).Replace("-", "").ToLowerInvariant();
            if (hash != want[2]) throw new Exception("The Python download wasn't the expected file, so it wasn't installed.");
            if (!Signature.By(exe, "Python Software Foundation"))
                throw new Exception("The Python download isn't signed by the Python Software Foundation, so it wasn't installed.");
            Ui.Progress("Installing Python " + App.PyVersion + " for you...", 22, "This takes a minute or two.");
            var p = Process.Start(new ProcessStartInfo(exe, "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 " +
                                                       "InstallLauncherAllUsers=0 Include_test=0 Include_doc=0") { UseShellExecute = false });
            int code = Ui.Wait(p, 40, 90);
            App.Log("Python installer exit code " + code);
            if (code != 0 && code != 3010) throw new Exception("Python's installer stopped (exit code " + code + ").");
        }
        finally { Files.TryDelete(exe); }
    }

    // ---- the folder

    // the folder it goes in: the one chosen, unless that already holds other things (then an <App> folder inside
    // it), so uninstalling can never take anything else with it
    static string ResolveDir(string chosen)
    {
        chosen = Environment.ExpandEnvironmentVariables(chosen).TrimEnd('\\');
        if (Directory.Exists(chosen) && Directory.EnumerateFileSystemEntries(chosen).Any()
            && !File.Exists(Path.Combine(chosen, App.InfoFile))
            && !string.Equals(Path.GetFileName(chosen), App.Name, StringComparison.OrdinalIgnoreCase))
            return Path.Combine(chosen, App.Name);
        return chosen;
    }

    // an error to show, or null if it can go there
    static string CheckFolder(string path)
    {
        if (string.IsNullOrEmpty(path) || !Path.IsPathRooted(Environment.ExpandEnvironmentVariables(path)))
            return "Choose a whole folder path, such as C:\\Users\\you\\Apps.";
        string dir = ResolveDir(path);
        foreach (var bad in new[] { Env("ProgramFiles"), Env("ProgramFiles(x86)"), Env("SystemRoot") })
            if (!string.IsNullOrEmpty(bad) && dir.StartsWith(bad, StringComparison.OrdinalIgnoreCase))
                return App.Name + " installs just for you, without asking for admin permission, so it can't go in " + bad +
                       ". Choose a folder of your own, such as the one it suggests.";
        try
        {
            Directory.CreateDirectory(dir);
            string probe = Path.Combine(dir, ".write-test-" + Process.GetCurrentProcess().Id);
            File.WriteAllText(probe, "ok"); File.Delete(probe);
        }
        catch { return App.Name + " can't write to " + dir + ". Choose another folder."; }
        return null;
    }

    // ---- the install

    public static int Begin()
    {
        App.LogHeader("installer");
        // the one-file download carries the program's files (Payload.cs); a folder beside it has them otherwise
        try { Src = Payload.Unpack() ?? App.Here; }
        catch (Exception e)
        {
            App.Log("ERROR: " + e);
            Ui.Error("The installer couldn't unpack " + App.Name + "'s files.\n\n" + e.Message + "\n\nWhat the installer did is in " + App.LogFile + ".");
            return 1;
        }
        Ui.Unattended = !string.IsNullOrEmpty(Env("SS_PHONES"));
        if (!File.Exists(Path.Combine(Src, "version.py")))
        {
            // an installer without the program's files, away from its folder
            Ui.Say("Extract the zip first: right-click it, choose Extract All, then open Install " + App.Name +
                   " in the extracted folder.");
            return 1;
        }
        try { return Steps(); }
        catch (Exception e)
        {
            App.Log("ERROR: " + e);
            // it was running before the update began: start that copy again
            string again = "";
            if (WasRunning != null && File.Exists(Path.Combine(WasRunning, App.Name + ".exe")))
            {
                Process.Start(new ProcessStartInfo(Path.Combine(WasRunning, App.Name + ".exe"), "--no-browser") { UseShellExecute = false, WorkingDirectory = WasRunning });
                again = "\n\nThe " + App.Name + " you already had is running again.";
                App.Log("restarted " + WasRunning);
            }
            Ui.Error(App.Name + " wasn't installed.\n\n" + e.Message + again + "\n\nWhat the installer did is in " + App.LogFile + ".");
            return 1;
        }
    }

    static int Steps()
    {
        Ui.Open("Install " + App.Name, Path.Combine(Src, @"docs\images\moon-pi-logo-128.png"),
                Path.Combine(Src, @"tools\launcher\" + App.Icon("app")), App.Name);
        App.Log("window shown");

        var py = FindPython();
        string intro = "A live aircraft radar, in your web browser. This installs " + App.Name + " for you on this PC; it runs quietly in the background, with a radar icon by the clock.";
        if (py == null) intro += "\n\nIt also installs Python " + App.PyVersion + " from python.org (about 36 MB), which " + App.Name + " runs on.";
        string was = App.InstalledDir();
        string suggest = Env("SS_DIR") ?? was ?? App.DefaultDir;

        // already installed? Then update (this one's newer), repair (the same) or reinstall from scratch
        string newVersion = Regex.Match(File.ReadAllText(Path.Combine(Src, "version.py")), "VERSION = \"([^\"]+)\"").Groups[1].Value;
        string have = was == null ? null : App.InstalledVersion(was);
        var fresh = new Mode("Reinstall from scratch", "Removes everything " + App.Name + " put on this PC, its settings too, then installs it new. Only your FlightAware API key is kept.");
        string compare = "Compares the installed files with this installer's and copies only the ones that differ. Your settings and FlightAware key are kept.";
        var buttons = new List<Mode>(); var modes = new List<string>();
        string modeIntro = null;
        if (have != null)
        {
            int n = App.Newer(newVersion, have);
            if (n > 0)
            {
                modeIntro = App.Name + " " + have + " is installed on this PC. This installer has version " + newVersion + ". What would you like to do?";
                buttons.Add(new Mode("Update to " + newVersion, compare)); modes.Add("update");
            }
            else if (n == 0)
            {
                modeIntro = App.Name + " " + have + " is already installed on this PC. What would you like to do?";
                buttons.Add(new Mode("Repair", "Checks every installed file and puts back any that are damaged or missing, then sets up its shortcuts again. Your settings and FlightAware key are kept."));
                modes.Add("repair");
            }
            else
            {
                modeIntro = "A newer " + App.Name + " (" + have + ") is installed on this PC than this installer's version (" + newVersion + "). Cancel keeps the newer one.";
                buttons.Add(new Mode("Install " + newVersion, compare)); modes.Add("update");
            }
            buttons.Add(fresh); modes.Add("fresh");
            if (py == null) modeIntro += " (It also installs Python " + App.PyVersion + " from python.org, which " + App.Name + " runs on.)";
        }
        bool wasPhones = was == null || App.InstalledFlag(was, "phones", true);
        bool wasAuto = was != null && App.InstalledFlag(was, "autostart", false);
        bool wasDesk = was == null || App.InstalledFlag(was, "desktop", true);
        string mode = "install";
        bool[] choices;
        while (true)
        {
            string text = intro, okText = "Install";
            if (have != null)
            {
                int pick = Ui.Modes(modeIntro, buttons);
                if (pick < 0) { Ui.Close(); return 0; }
                mode = modes[pick];
                if (Ui.Unattended && Env("SS_MODE") != null) mode = Env("SS_MODE");
                okText = mode == "update" ? "Update" : mode == "repair" ? "Repair" : "Reinstall";
                string doing = mode == "update" ? "Updating " + App.Name + " " + have + " to " + newVersion
                             : mode == "repair" ? "Repairing " + App.Name + " " + have
                             : "Reinstalling " + App.Name + " " + newVersion + " from scratch";
                text = doing + ": " + buttons[Math.Max(0, modes.IndexOf(mode))].Note + "\n\nChoose below, then click " + okText + " (or Back to choose differently).";
            }
            choices = Ui.Choices(text, new[] {
                new Box(App.PhonesText, Env("SS_PHONES") != null ? Env("SS_PHONES") != "no" : wasPhones),
                new Box("Start " + App.Name + " when I sign in to Windows", Env("SS_AUTOSTART") != null ? Env("SS_AUTOSTART") == "yes" : wasAuto),
                new Box("Put Start and Stop " + App.Name + " on the Desktop", Env("SS_DESKTOP") != null ? Env("SS_DESKTOP") != "no" : wasDesk) },
                okText, have != null, suggest, CheckFolder);
            if (!Ui.WentBack) break;
        }
        if (choices == null) { Ui.Close(); return 0; }
        bool phones = choices[0], autostart = choices[1], onDesktop = choices[2];
        string problem = CheckFolder(Ui.Folder);
        if (problem != null) throw new Exception(problem);
        AppDir = ResolveDir(Ui.Folder);
        App.Log("mode=" + mode + " (" + have + " -> " + newVersion + ") folder=" + AppDir + " phones=" + phones + " autostart=" + autostart + " desktop=" + onDesktop);

        Ui.Progress("Checking the internet connection...", 1);
        if (!Web.Online())
            throw new Exception("Installing needs an internet connection, to download what " + App.Name + " runs on from python.org and " +
                                "pypi.org, and this PC can't reach them. Nothing was changed" + (was != null ? ": the " + App.Name + " you have keeps working" : "") +
                                ". Connect to the internet, then run the installer again.");

        if (py == null)
        {
            if (Env("SS_PYTHON") == "no") throw new Exception(App.Name + " needs Python " + App.PythonMin + " or newer, and this PC doesn't have it.");
            InstallPython();
            py = FindPython();
            if (py == null) throw new Exception("Python was installed but can't be found. Restart the PC and run the installer again.");
        }

        // an update: stop the running copy first (also one in another folder, when it's moving)
        Ui.Progress("Getting ready...", 42);
        var others = new List<string>();
        if (was != null && !string.Equals(was, AppDir, StringComparison.OrdinalIgnoreCase) && Directory.Exists(was)) others.Add(was);
        foreach (var d in new[] { AppDir }.Concat(others))
        {
            if (!File.Exists(Path.Combine(d, App.InfoFile))) continue;
            if (Web.Up(App.InstalledPort(d))) WasRunning = d;     // (if this install goes wrong after this, it's started again)
            App.Log("stopping the copy in " + d);
            Runner.Stop(d, true);
        }

        var notes = new List<string>();
        string check = Path.Combine(Src, @"installer\filecheck.py");
        Environment.SetEnvironmentVariable("FC_APP", App.Name);
        if (mode == "fresh")
        {
            // from scratch: everything it put on this PC goes (the program, its settings, Python set-up, shortcuts,
            // Settings > Apps entry), except the FlightAware key, which comes back below as after an uninstall
            Ui.Progress("Removing everything " + App.Name + " put on this PC...", 44);
            foreach (var d in new[] { AppDir }.Concat(others))
            {
                string settings = Path.Combine(d, "settings.json");
                if (File.Exists(settings))
                {
                    try { Run(py.Exe, py.With(Path.Combine(Src, @"installer\keep_key.py"), "save", settings, App.KeptKey), "Keeping the FlightAware key", 44, 10); }
                    catch (Exception e) { App.Log(e.Message + " - the FlightAware key couldn't be kept"); }
                }
                if (File.Exists(Path.Combine(d, App.InfoFile))) { Files.TryDeleteDir(d); App.Log("removed " + d); }
            }
            Shortcuts.RemoveAll();
            Registry.CurrentUser.DeleteSubKeyTree(App.UninstallKey, false);
            notes.Add("Everything was removed and installed new, with " + App.Name + "'s own settings" + (File.Exists(App.KeptKey) ? ", except your FlightAware API key." : "."));
            others.Clear();
        }
        Directory.CreateDirectory(AppDir);
        // moving: your settings and the like come along
        foreach (var d in others)
            foreach (var f in App.Keep)
            {
                string from = Path.Combine(d, f), to = Path.Combine(AppDir, f);
                if (File.Exists(from) && !File.Exists(to)) File.Copy(from, to);
                else if (Directory.Exists(from) && !Directory.Exists(to)) Files.CopyDir(from, to);
            }

        string venvPy = Path.Combine(AppDir, @"venv\Scripts\python.exe");
        var pipArgs = new[] { "--disable-pip-version-check", "--no-input", "--progress-bar", "off" };
        Action newVenv = () =>
        {
            Ui.Progress("Setting up Python for " + App.Name + "...", 45);
            Files.TryDeleteDir(Path.Combine(AppDir, "venv"));
            Run(py.Exe, py.With("-m", "venv", Path.Combine(AppDir, "venv")), "Setting up Python", 50, 20);
            try { Run(venvPy, new[] { "-m", "pip", "install", "--quiet", "--upgrade", "pip" }.Concat(pipArgs), "Updating pip", 52, 20); }
            catch (Exception e) { App.Log(e.Message + " - carrying on with the pip it has"); }
        };
        // a fresh environment if there's none, its Python was removed or is too old, or it can't run its own pip
        bool venvOk = File.Exists(venvPy)
            && Proc.Quick(venvPy, new[] { "-c", "import sys; sys.exit(sys.version_info < (" + App.PythonMin.Major + ", " + App.PythonMin.Minor + "))" }) == 0
            && Proc.Quick(venvPy, new[] { "-m", "pip", "--version" }) == 0;
        if (File.Exists(venvPy) && !venvOk) App.Log(App.Name + "'s Python set-up can't run: making it again");
        if (!venvOk) newVenv();
        Func<string, string> summary = t => Regex.Replace(LastLine(t), "^Checked", "checked");
        if (mode == "repair")
        {
            // every file of its Python parts against the fingerprint pip wrote down; packages with damaged or missing
            // files are installed again (all of the Python set-up, if that doesn't fix them)
            Ui.Progress("Checking " + App.Name + "'s Python parts...", 52);
            string found = Run(venvPy, new[] { check, "check" }, "Checking the installed Python parts", 56, 120, 0, 1);
            string more = "";
            if (LastCode != 0)
            {
                bool fixedAll = true;
                foreach (var line in found.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).Where(l => l.StartsWith("REPAIR ")))
                {
                    string want = line.Substring(7).Trim();
                    try { Run(venvPy, new[] { "-m", "pip", "install", "--force-reinstall", "--no-deps", want }.Concat(pipArgs), "Installing " + want + " again", 58, 60); }
                    catch (Exception e) { App.Log(e.Message); fixedAll = false; }
                }
                if (fixedAll) { Run(venvPy, new[] { check, "check" }, "Checking them again", 59, 120, 0, 1); fixedAll = LastCode == 0; }
                if (!fixedAll) { App.Log("some files could not be fixed in place: making the Python set-up again"); newVenv(); more = " Its Python parts were set up again to fix them."; }
            }
            notes.Add("Repair " + summary(found) + more);
        }
        // what it runs on: only installed if it's missing (an update or repair keeps what's there)
        double at = 60;
        foreach (var pkg in App.Packages)
        {
            Ui.Progress(pkg[1], at, pkg[3]);
            double upTo = at + 16.0 / App.Packages.Length;      // (the packages share 60% to 76%)
            try { Run(venvPy, new[] { "-m", "pip", "install" }.Concat(pkg[0].Split(' ')).Concat(pipArgs), "Installing " + pkg[0], upTo, 60); }
            catch (Exception e) { if (pkg[2] == "yes") throw; App.Log(e.Message + " - carrying on without " + pkg[0]); }
            at = upTo;
        }

        // the program: each file compared with this installer's, and only those that are damaged, missing or
        // different are copied (installed-files.json lists them, so files a new version doesn't have go); settings
        // stay. (An install from before that list: its program files are all replaced.)
        Ui.Progress(mode == "repair" ? "Checking " + App.Name + "'s program files..." : "Copying " + App.Name + "...", 77);
        if (!File.Exists(Path.Combine(AppDir, "installed-files.json")))
        {
            foreach (var d in new[] { "web", "data", "docs" }) Files.TryDeleteDir(Path.Combine(AppDir, d));
            foreach (var f in Directory.GetFiles(AppDir, "*.py")) Files.TryDelete(f);
        }
        string synced = Run(venvPy, new[] { check, "sync", mode == "repair" ? "repair" : "update", Src, AppDir }.Concat(App.ProgramItems),
                            "Copying the program", 77, 60, 0, 1);
        if (mode == "repair" || (have != null && mode != "fresh")) notes.Add(LastLine(synced));
        // the Windows programs and their icons
        string win = Path.Combine(Src, @"installer\windows");
        Put(Path.Combine(win, "run.py"), Path.Combine(AppDir, "run.py"));
        foreach (var exe in new[] { App.Name + ".exe", "Uninstall " + App.Name + ".exe" })
            Put(Path.Combine(win, exe), Path.Combine(AppDir, exe));
        foreach (var ico in new[] { App.Icon("start"), App.Icon("stop"), App.Icon("uninstall"), App.Icon("app") })
            Put(Path.Combine(Src, @"tools\launcher\" + ico), Path.Combine(AppDir, ico));
        Put(Path.Combine(Src, @"docs\images\moon-pi-logo-128.png"), Path.Combine(AppDir, "logo.png"));
        // what the PowerShell installers (before 1.7) left: their scripts, and Python renamed for Task Manager
        foreach (var old in new[] { "start.ps1", "stop.ps1", "uninstall.ps1", "firewall.ps1", "ui.ps1", @"venv\Scripts\" + App.Name + ".exe" })
            Files.TryDelete(Path.Combine(AppDir, old));
        // a FlightAware key kept when it was last uninstalled comes back
        if (File.Exists(App.KeptKey))
        {
            try { Run(venvPy, new[] { Path.Combine(Src, @"installer\keep_key.py"), "restore", Path.Combine(AppDir, "settings.json"), App.KeptKey }, "Bringing back the FlightAware key", 77, 10); }
            catch (Exception e) { App.Log(e.Message + " - the kept FlightAware key stays where it is"); }
        }
        Files.Unblock(AppDir);     // drop the "downloaded from the internet" mark on our copies

        string version = Regex.Match(File.ReadAllText(Path.Combine(AppDir, "version.py")), "VERSION = \"([^\"]+)\"").Groups[1].Value;
        int port = App.PortOf(AppDir);
        Json.Write(Path.Combine(AppDir, App.InfoFile), new Dictionary<string, object> {
            { "port", port }, { "phones", phones }, { "autostart", autostart }, { "desktop", onDesktop },
            { "version", version }, { "exe", Path.Combine(AppDir, App.Name + ".exe") } });

        // shortcuts: the Start menu, the Desktop if wanted (Start and Stop only), and the Startup folder when it
        // should start at sign-in
        Ui.Progress("Adding the shortcuts...", 86);
        Shortcuts.Make(AppDir, onDesktop, autostart);

        // Settings > Apps (and Control Panel > Programs) list it, with an Uninstall button
        Ui.Progress("Listing " + App.Name + " in Settings > Apps...", 87);
        string uninstall = "\"" + Path.Combine(AppDir, "Uninstall " + App.Name + ".exe") + "\"";
        using (var k = Registry.CurrentUser.CreateSubKey(App.UninstallKey))
        {
            k.SetValue("DisplayName", App.Name);
            k.SetValue("DisplayVersion", version);
            k.SetValue("Publisher", "Project Moon Pi");
            k.SetValue("DisplayIcon", Path.Combine(AppDir, App.Icon("app")));
            k.SetValue("InstallLocation", AppDir);
            k.SetValue("UninstallString", uninstall);
            k.SetValue("QuietUninstallString", uninstall + " -Quiet");
            k.SetValue("URLInfoAbout", App.Url);
            k.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
            k.SetValue("NoModify", 1, RegistryValueKind.DWord);
            k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            k.SetValue("EstimatedSize", (int)(Files.SizeOf(AppDir) / 1024), RegistryValueKind.DWord);
        }

        // moved from another folder: it's stopped, its settings came along and everything else has been replaced
        foreach (var d in others) if (File.Exists(Path.Combine(d, App.InfoFile))) Files.TryDeleteDir(d);

        // phones and Satellites: make sure the firewall lets them in on home networks (Windows asks for
        // permission only if needed, and a note says so first)
        string networkNote = null;
        if (phones)
        {
            Ui.Progress("Letting " + App.PhonesShort + " on your home network reach " + App.Name + "...", 89);
            string state = Firewall.Ensure(port, BasePythonW(AppDir), Ui.Unattended);
            App.Log("firewall: " + state);
            if (state == "Declined")
                networkNote = "Windows didn't allow the firewall change, so " + App.PhonesShort + " can't reach " + App.Name + " yet. Run the installer again and click Yes when Windows asks.";
            else if (state != "AllowedPublic" && Firewall.OnPublicNetwork())
                networkNote = "This PC's network is set to Public, where Windows keeps other devices out. For " + App.PhonesShort + " to reach " + App.Name + ", set your home Wi-Fi to Private: Settings > Network & Internet > (your connection) > Private.";
        }
        else Firewall.Remove(port, Ui.Unattended);
        if (networkNote != null) App.Log(networkNote);

        Ui.Progress("Starting " + App.Name + "...", 90);
        var start = new ProcessStartInfo(Path.Combine(AppDir, App.Name + ".exe"), "--no-browser") { UseShellExecute = false, WorkingDirectory = AppDir };
        start.EnvironmentVariables["SS_INSTALLING"] = "1";      // (Start needn't put up its own notice)
        Ui.Wait(Process.Start(start), 100, 30);
        bool up = Web.Up(port, 5000);
        App.Log("installed " + version + ", running=" + up);

        string did = mode == "update" ? "is installed (updated from " + have + ")" : mode == "repair" ? "is repaired"
                   : mode == "fresh" ? "is reinstalled from scratch" : "is installed";
        string done = App.Name + " " + version + " " + did + (up ? " and running." : ", but it didn't start yet: use Start " + App.Name + " in the Start menu.") +
            "\n\nIts radar icon is by the clock (click ^ if Windows has tucked it away there): click it for the radar, right-click for the settings or Stop. Start and Stop " +
            App.Name + " are in the Start menu" + (onDesktop ? ", and on your Desktop" : "") + ". To remove it, use Remove " + App.Name +
            " in the Start menu, Uninstall " + App.Name + " in " + AppDir + ", or Settings > Apps." +
            (networkNote != null ? "\n\n" + networkNote : "") + string.Concat(notes.Select(n => "\n\n" + n));
        var open = Ui.Done(done, "Finish", new[] { new Box("Open the radar now", up && Env("SS_OPEN") != "no") });
        if (up && open.Length > 0 && open[0] && !Ui.Unattended) Proc.Open("http://127.0.0.1:" + port + App.OpenPath);
        return 0;
    }

    // A file copied into the install folder. Windows refusing a file that isn't there is usually an antivirus
    // program that removed it from an earlier install (Bitdefender, after it blocked the PowerShell installers
    // before 1.7, keeps refusing that path until it's cleared and the PC restarts): say so, rather than "denied".
    static void Put(string from, string to)
    {
        try { File.Copy(from, to, true); }
        catch (UnauthorizedAccessException) when (!File.Exists(to))
        {
            throw new Exception("Windows wouldn't let the installer create " + to + ". That's usually an antivirus program " +
                                "that removed this file from an earlier install and still blocks it. Open your antivirus " +
                                "program's quarantine, delete the " + App.Name + " files listed there, restart the PC, " +
                                "then run the installer again.");
        }
    }

    // the Python program that actually listens (a venv's pythonw.exe starts its base Python's): the firewall's
    // "allow this app?" rules name that one
    static string BasePythonW(string dir)
    {
        try
        {
            foreach (var line in File.ReadAllLines(Path.Combine(dir, @"venv\pyvenv.cfg")))
            {
                var m = Regex.Match(line, @"^\s*home\s*=\s*(.+?)\s*$");
                if (m.Success) return Path.Combine(m.Groups[1].Value, "pythonw.exe");
            }
        }
        catch { }
        return Runner.PythonW(dir);
    }
}

// Is a file signed (and the signature good, by Windows' own check) by this organisation?
static class Signature
{
    public static bool By(string file, string organisation)
    {
        try
        {
            if (Verify(file) != 0) return false;
            var cert = new X509Certificate2(X509Certificate.CreateFromSignedFile(file));
            return Regex.IsMatch(cert.Subject, "O=\"?" + Regex.Escape(organisation));
        }
        catch { return false; }
    }

    static int Verify(string file)
    {
        var fileInfo = new WINTRUST_FILE_INFO { cbStruct = (uint)Marshal.SizeOf(typeof(WINTRUST_FILE_INFO)), pcwszFilePath = file };
        IntPtr pFile = Marshal.AllocHGlobal(Marshal.SizeOf(fileInfo));
        Marshal.StructureToPtr(fileInfo, pFile, false);
        var data = new WINTRUST_DATA
        {
            cbStruct = (uint)Marshal.SizeOf(typeof(WINTRUST_DATA)), dwUIChoice = 2 /* none */, fdwRevocationChecks = 0,
            dwUnionChoice = 1 /* file */, pFile = pFile, dwStateAction = 0, dwProvFlags = 0x10 /* safer */,
        };
        IntPtr pData = Marshal.AllocHGlobal(Marshal.SizeOf(data));
        Marshal.StructureToPtr(data, pData, false);
        try
        {
            var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");      // WINTRUST_ACTION_GENERIC_VERIFY_V2
            return WinVerifyTrust(new IntPtr(-1), ref action, pData);
        }
        finally { Marshal.FreeHGlobal(pData); Marshal.FreeHGlobal(pFile); }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WINTRUST_FILE_INFO { public uint cbStruct; public string pcwszFilePath; public IntPtr hFile; public IntPtr pgKnownSubject; }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WINTRUST_DATA
    {
        public uint cbStruct; public IntPtr pPolicyCallbackData, pSIPClientData; public uint dwUIChoice, fdwRevocationChecks, dwUnionChoice;
        public IntPtr pFile; public uint dwStateAction; public IntPtr hWVTStateData; public IntPtr pwszURLReference;
        public uint dwProvFlags, dwUIContext; public IntPtr pSignatureSettings;
    }

    [DllImport("wintrust.dll", CharSet = CharSet.Unicode)] static extern int WinVerifyTrust(IntPtr hwnd, ref Guid action, IntPtr data);
}
