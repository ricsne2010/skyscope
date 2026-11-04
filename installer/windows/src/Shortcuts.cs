// The app's shortcuts: Start and Stop in the Start menu (and on the Desktop if wanted), Remove <App> in the Start menu,
// and Start at sign-in in the Startup folder when it should. All of them open <App>.exe in the install folder.
// Designed and Created by Project Moon Pi.
using System;
using System.IO;

static class Shortcuts
{
    static string Desktop { get { return Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory); } }
    static string Menu { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), App.Name); } }
    static string Startup { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), App.Name + ".lnk"); } }

    static void Make(string path, string dir, string args, string icon, string description)
    {
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        dynamic s = shell.CreateShortcut(path);
        s.TargetPath = Path.Combine(dir, App.Name + ".exe");
        s.Arguments = args;
        s.IconLocation = Path.Combine(dir, icon) + ",0";
        s.WorkingDirectory = dir;
        s.Description = description;
        s.Save();
    }

    public static void Make(string dir, bool onDesktop, bool atSignIn)
    {
        string lower = App.Name.ToLowerInvariant();
        Directory.CreateDirectory(Menu);
        var places = onDesktop ? new[] { Menu, Desktop } : new[] { Menu };
        if (!onDesktop) { Files.TryDelete(Path.Combine(Desktop, "Start " + App.Name + ".lnk")); Files.TryDelete(Path.Combine(Desktop, "Stop " + App.Name + ".lnk")); }
        Files.TryDelete(Path.Combine(Desktop, "Uninstall " + App.Name + ".lnk"));     // (1.6.1 put one there)
        foreach (var place in places)
        {
            Make(Path.Combine(place, "Start " + App.Name + ".lnk"), dir, "", lower + "-start.ico", "Start " + App.Name + " and open it");
            Make(Path.Combine(place, "Stop " + App.Name + ".lnk"), dir, "--stop", lower + "-stop.ico", "Stop " + App.Name);
        }
        // Remove <App>: two things keep Windows' Start menu from hiding it (found in the Win11 VM): no description
        // (one about removing the program hides it), and a new command on every install (--installed <time>), made
        // as a new shortcut: Windows remembers a Remove shortcut that went with an uninstall and hides any later one
        // with the same command. It opens <App>.exe, which opens the uninstaller: a shortcut straight to a program
        // named Uninstall... is hidden too.
        Files.TryDelete(Path.Combine(Menu, "Uninstall " + App.Name + ".lnk"));
        Files.TryDelete(Path.Combine(Menu, "Remove " + App.Name + ".lnk"));
        Make(Path.Combine(Menu, "Remove " + App.Name + ".lnk"), dir, "--uninstall --installed " + DateTime.Now.ToString("yyyyMMddHHmmss"),
             lower + "-uninstall.ico", "");
        if (atSignIn) Make(Startup, dir, "--no-browser", lower + "-start.ico", "Start " + App.Name + " at sign-in");
        else Files.TryDelete(Startup);
    }

    public static void RemoveAll()
    {
        foreach (var name in new[] { "Start", "Stop", "Uninstall" }) Files.TryDelete(Path.Combine(Desktop, name + " " + App.Name + ".lnk"));
        Files.TryDelete(Startup);
        Files.TryDeleteDir(Menu);
    }
}
