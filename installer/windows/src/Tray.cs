// <App>.exe --tray: the app's icon by the clock. It stays while you're signed in, whether the app runs or not: green
// while it runs, red when it's stopped ("Starting..." in its tooltip and a notice while it starts), so it can be
// started again from there. Its menu: Open <page> (also a left click), Start and Stop <App> Service. Those only
// start and stop the app in the background, as the Start menu's Start and Stop do.
// One at a time (a named mutex); Start <App> opens it when it isn't there. The installer and uninstaller close it
// (Runner.Stop with closeTray), so <App>.exe can be replaced or removed.
// Designed and Created by Project Moon Pi.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Windows.Forms;

static class Tray
{
    static string MutexName { get { return "Local\\" + App.Id + ".Tray"; } }
    public static string QuitSignal { get { return "Local\\" + App.Id + ".TrayQuit"; } }
    public static string PidFile(string dir) { return Path.Combine(dir, App.Slug + "-tray.pid"); }

    // is the icon there now?
    public static bool Running
    {
        get
        {
            Mutex m;
            if (!Mutex.TryOpenExisting(MutexName, out m)) return false;
            m.Dispose();
            return true;
        }
    }

    // opens the icon if it isn't there (from <App>.exe in the install folder)
    public static void Ensure(string dir)
    {
        if (Running) return;
        try { Process.Start(new ProcessStartInfo(Path.Combine(dir, App.Name + ".exe"), "--tray") { UseShellExecute = false, WorkingDirectory = dir }); }
        catch (Exception e) { App.Log("the icon by the clock didn't open: " + e.Message); }
    }

    // the installer and uninstaller: the icon goes (so the program can be replaced or removed)
    public static void Close(string dir)
    {
        try { using (var e = EventWaitHandle.OpenExisting(QuitSignal)) e.Set(); } catch { }
        try
        {
            int id = int.Parse(File.ReadAllText(PidFile(dir)).Trim());
            var p = Process.GetProcessById(id);
            if (!p.WaitForExit(5000)) p.Kill();
        }
        catch { }
        Files.TryDelete(PidFile(dir));
    }

    static Icon Load(string dir, string kind, Icon fallback)
    {
        try
        {
            string f = Path.Combine(dir, App.Icon(kind));
            if (File.Exists(f)) return new Icon(f, SystemInformation.SmallIconSize);
        }
        catch { }
        return fallback;
    }

    enum State { Unknown, Stopped, Starting, Running, Stopping }

    public static int Run(string dir)
    {
        bool mine;
        using (var only = new Mutex(true, MutexName, out mine))
        {
            if (!mine) return 0;                                   // (it's there already)
            try { File.WriteAllText(PidFile(dir), Process.GetCurrentProcess().Id.ToString()); } catch { }
            Application.EnableVisualStyles();
            int port = App.InstalledPort(dir);
            string url = "http://127.0.0.1:" + port + App.OpenPath;
            Icon app = SystemIcons.Application;
            try { app = Icon.ExtractAssociatedIcon(App.Exe); } catch { }
            Icon on = Load(dir, "tray-on", app), off = Load(dir, "tray-off", app);

            var menu = new ContextMenuStrip();
            var open = new ToolStripMenuItem("Open " + App.PageName) { Font = new Font(menu.Font, FontStyle.Bold) };
            var start = new ToolStripMenuItem("Start " + App.Name + " Service");
            var stop = new ToolStripMenuItem("Stop " + App.Name + " Service");
            menu.Items.AddRange(new ToolStripItem[] { open, new ToolStripSeparator(), start, stop });
            var icon = new NotifyIcon { Icon = off, Text = App.Name, ContextMenuStrip = menu, Visible = true };
            var ui = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();

            State state = State.Unknown;
            State asked = State.Unknown;                           // Start or Stop clicked here, until it's done
            DateTime askedAt = DateTime.MinValue;
            int checking = 0;

            Action<State> show = s =>
            {
                State was = state;
                state = s;
                bool up = s == State.Running;
                icon.Icon = up ? on : off;
                string words = s == State.Running ? "running" : s == State.Starting ? "starting..." : s == State.Stopping ? "stopping..." : "stopped";
                icon.Text = App.Name + ": " + words;
                start.Enabled = s == State.Stopped;
                stop.Enabled = s == State.Running || s == State.Starting;
                open.Enabled = s != State.Stopping;
                if (was == State.Unknown || was == s) return;
                if (s == State.Running) icon.ShowBalloonTip(4000, App.Name, App.Name + " is running.", ToolTipIcon.Info);
                else if (s == State.Stopped) icon.ShowBalloonTip(4000, App.Name, App.Name + " has stopped. Start it again from this icon.", ToolTipIcon.Info);
                else if (s == State.Starting && App.StartingNote != null) icon.ShowBalloonTip(5000, App.Name, App.StartingNote, ToolTipIcon.Info);
            };

            // every 2 seconds, away from the window: is it answering, or has it been started and not answering yet?
            var timer = new System.Windows.Forms.Timer { Interval = 2000 };
            timer.Tick += (s, e) =>
            {
                if (Interlocked.Exchange(ref checking, 1) == 1) return;
                ThreadPool.QueueUserWorkItem(_ =>
                {
                    State now;
                    try
                    {
                        if (Web.Up(port, 800)) now = State.Running;
                        else if (Runner.HostProcess(dir) != null) now = State.Starting;
                        else now = State.Stopped;
                    }
                    catch { now = State.Stopped; }
                    ui.Post(__ =>
                    {
                        checking = 0;
                        // what was clicked shows until it's done (or a minute or so has passed)
                        bool waiting = (DateTime.Now - askedAt).TotalSeconds < Math.Max(60, App.StartSeconds);
                        if (asked == State.Starting && now == State.Stopped && waiting) now = State.Starting;
                        if (asked == State.Stopping && now != State.Stopped && waiting) now = State.Stopping;
                        if (now == State.Running || now == State.Stopped) asked = State.Unknown;
                        if (now != state) show(now);
                    }, null);
                });
            };

            Action<string> launch = args =>
            {
                try { Process.Start(new ProcessStartInfo(Path.Combine(dir, App.Name + ".exe"), args) { UseShellExecute = false, WorkingDirectory = dir }); }
                catch (Exception e) { MessageBox.Show(e.Message, App.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning); }
            };
            Action doStart = () => { asked = State.Starting; askedAt = DateTime.Now; show(State.Starting); launch("--no-browser"); };
            Action doOpen = () =>
            {
                if (state == State.Running) Proc.Open(url);
                else { asked = State.Starting; askedAt = DateTime.Now; show(State.Starting); launch(""); }   // (starts it, then opens it)
            };
            open.Click += (s, e) => doOpen();
            start.Click += (s, e) => doStart();
            stop.Click += (s, e) => { asked = State.Stopping; askedAt = DateTime.Now; show(State.Stopping); launch("--stop --quiet"); };
            icon.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left && state != State.Stopping) doOpen(); };

            // closed by the installer or uninstaller
            var quit = new EventWaitHandle(false, EventResetMode.AutoReset, QuitSignal);
            var waiter = new Thread(() => { quit.WaitOne(); ui.Post(_ => Application.ExitThread(), null); }) { IsBackground = true };
            waiter.Start();

            show(Web.Up(port, 800) ? State.Running : Runner.HostProcess(dir) != null ? State.Starting : State.Stopped);
            timer.Start();
            Application.Run();
            timer.Stop();
            icon.Visible = false;
            icon.Dispose();
            Files.TryDelete(PidFile(dir));
            return 0;
        }
    }
}
