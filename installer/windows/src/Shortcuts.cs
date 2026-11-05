// The app's shortcuts (App.Links: Open, Start and Stop, or Play) in the Start menu and on the Desktop if wanted, and
// Start at sign-in in the Startup folder when it should. All of them open <App>.exe in the install folder. No Remove
// shortcut: it's removed from Settings > Apps, as other programs are.
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
        // the Start menu folder made new (so earlier versions' shortcuts, Remove <App> and Start <App>, go), and
        // earlier versions' Start and Stop <App> on the Desktop
        Files.TryDeleteDir(Menu);
        Directory.CreateDirectory(Menu);
        foreach (var old in new[] { "Start " + App.Name, "Stop " + App.Name }) Files.TryDelete(Path.Combine(Desktop, old + ".lnk"));
        var places = onDesktop ? new[] { Menu, Desktop } : new[] { Menu };
        if (!onDesktop) foreach (var l in App.Links) Files.TryDelete(Path.Combine(Desktop, l[0] + ".lnk"));
        Files.TryDelete(Path.Combine(Desktop, "Uninstall " + App.Name + ".lnk"));     // (earlier versions put one there)
        foreach (var place in places)
            foreach (var l in App.Links) Make(Path.Combine(place, l[0] + ".lnk"), dir, l[1], App.Icon(l[2]), l[3]);
        if (atSignIn) Make(Startup, dir, "--no-browser", App.Icon("start"), "Start " + App.Display + " at sign-in");
        else Files.TryDelete(Startup);
    }

    public static void RemoveAll()
    {
        foreach (var l in App.Links) Files.TryDelete(Path.Combine(Desktop, l[0] + ".lnk"));
        foreach (var old in new[] { "Start " + App.Name, "Stop " + App.Name, "Uninstall " + App.Name })
            Files.TryDelete(Path.Combine(Desktop, old + ".lnk"));
        Files.TryDelete(Startup);
        Files.TryDeleteDir(Menu);
    }
}
