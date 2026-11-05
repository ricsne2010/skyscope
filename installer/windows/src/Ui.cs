// The installer's and uninstaller's window: the Project Moon Pi logo and the app's name across the top, then a page
// below it (choices, a progress bar, or done). Pages:
//   Ui.Open(title, logo, icon, name)
//   Ui.Choices(text, boxes, okText, back, folder, folderCheck, textHeight)  -> the boxes' states, or null on Cancel/Back
//       (Ui.WentBack says which; the chosen folder is then in Ui.Folder)
//   Ui.Modes(text, choices)       -> the number of the big button clicked, or -1 on Cancel
//   Ui.Progress(text, percent, detail)   moves the bar smoothly towards percent and says what's happening
//   Ui.Wait(process, upTo, seconds)      keeps the window alive while a program runs, the bar creeping on
//   Ui.Done(text, okText, boxes)  the last page; the boxes' states when closed
//   Ui.Error(text)
// With Ui.Unattended set, nothing waits for a click (the pages flash by). Designed and Created by Project Moon Pi.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

class Box
{
    public string Text; public bool Checked;
    public Box(string text, bool on) { Text = text; Checked = on; }
}

class Mode
{
    public string Label, Note;
    public Mode(string label, string note) { Label = label; Note = note; }
}

static class Ui
{
    public static bool Unattended;
    public static string Folder;
    public static bool WentBack;
    static Form form;
    static Label text, detail;
    static ProgressBar bar;
    static Button ok, cancel, back;
    static Panel body;
    static TextBox folderBox;
    static readonly List<CheckBox> boxes = new List<CheckBox>();
    static readonly List<Control> extra = new List<Control>();
    static string clicked;
    static int target;
    static bool closed;
    static System.Windows.Forms.Timer timer;

    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();

    public static Form Window { get { return form; } }
    public static bool IsOpen { get { return form != null && !closed; } }

    static Image ImageFile(string path)
    {
        // read into memory, so the uninstaller can delete the file
        try { return File.Exists(path) ? Image.FromStream(new MemoryStream(File.ReadAllBytes(path))) : null; } catch { return null; }
    }

    public static void Open(string title, string logo, string icon, string appName)
    {
        try { SetProcessDPIAware(); } catch { }        // sharp text on scaled displays
        Application.EnableVisualStyles();
        form = new Form
        {
            Text = title, AutoScaleDimensions = new SizeF(96, 96), AutoScaleMode = AutoScaleMode.Dpi,
            ClientSize = new Size(560, 540), StartPosition = FormStartPosition.CenterScreen,
            FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, BackColor = Color.White,
            Font = new Font("Segoe UI", 9.75f),
        };
        try { if (File.Exists(icon)) form.Icon = new Icon(new MemoryStream(File.ReadAllBytes(icon))); } catch { }

        // header: logo, name and credit on night blue
        var head = new Panel { Dock = DockStyle.Top, Height = 104, BackColor = Color.FromArgb(10, 22, 46) };
        var img = ImageFile(logo);
        if (img != null) head.Controls.Add(new PictureBox { Left = 20, Top = 12, Width = 80, Height = 80, SizeMode = PictureBoxSizeMode.Zoom, Image = img });
        head.Controls.Add(new Label { Left = 116, Top = 24, Width = 420, Height = 34, Text = appName, ForeColor = Color.White,
                                      Font = new Font("Segoe UI Semibold", 17f) });
        head.Controls.Add(new Label { Left = 118, Top = 60, Width = 420, Height = 22, Text = "Designed and Created by Project Moon Pi",
                                      ForeColor = Color.FromArgb(170, 185, 210) });

        // page: its text, then whatever the page needs; buttons at the bottom right
        body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(24, 18, 24, 0) };
        text = new Label { Left = 24, Top = 18, Width = 512, Height = 96, UseMnemonic = false };   // (an & is shown, not a shortcut)
        bar = new ProgressBar { Left = 24, Top = 120, Width = 512, Height = 20, Style = ProgressBarStyle.Continuous, Maximum = 1000, Visible = false };
        detail = new Label { Left = 24, Top = 148, Width = 512, Height = 40, Visible = false, UseMnemonic = false, ForeColor = Color.FromArgb(100, 100, 110) };
        ok = new Button { Width = 104, Height = 32, Left = 432, Top = 380, Visible = false };
        cancel = new Button { Width = 104, Height = 32, Left = 316, Top = 380, Text = "Cancel", Visible = false };
        back = new Button { Width = 104, Height = 32, Left = 24, Top = 380, Text = "< Back", Visible = false };
        body.Controls.AddRange(new Control[] { text, bar, detail, ok, cancel, back });
        form.Controls.AddRange(new Control[] { body, head });

        ok.Click += (s, e) => clicked = "ok";
        cancel.Click += (s, e) => clicked = "cancel";
        back.Click += (s, e) => clicked = "back";
        form.FormClosing += (s, e) =>
        {
            // the window's X: as Cancel while choosing; ignored while working
            if (ok.Visible || cancel.Visible) clicked = "cancel";
            else if (!closed) e.Cancel = true;
        };
        // the bar glides towards its target rather than jumping
        timer = new System.Windows.Forms.Timer { Interval = 15 };
        timer.Tick += (s, e) =>
        {
            if (bar.Value < target) bar.Value = Math.Min(target, bar.Value + Math.Max(1, (target - bar.Value) / 12));
        };
        timer.Start();
        form.Show();
        // In front: opened by a program in the background (SkyScope's Update to <version>), Windows would leave the
        // window behind the browser, flashing on the taskbar. It stays on top until it's first clicked (or for 20
        // seconds), and asks for the keyboard as Windows allows: through the window that has it now.
        form.TopMost = true;
        Front(form.Handle);
        var ends = DateTime.Now.AddSeconds(20);
        var topTimer = new System.Windows.Forms.Timer { Interval = 250 };
        topTimer.Tick += (s, e) =>
        {
            if (form.ContainsFocus || DateTime.Now > ends || closed) { form.TopMost = false; topTimer.Stop(); }
        };
        topTimer.Start();
        Pump();
    }

    static void Front(IntPtr window)
    {
        try
        {
            IntPtr fore = GetForegroundWindow();
            uint foreThread = GetWindowThreadProcessId(fore, IntPtr.Zero), mine = GetCurrentThreadId();
            if (foreThread != 0 && foreThread != mine) AttachThreadInput(mine, foreThread, true);
            BringWindowToTop(window);
            SetForegroundWindow(window);
            if (foreThread != 0 && foreThread != mine) AttachThreadInput(mine, foreThread, false);
        }
        catch { }
    }

    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, IntPtr processId);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint from, uint to, bool attach);
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr window);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);

    public static void Pump() { Application.DoEvents(); }

    static void Clear()
    {
        foreach (var c in boxes.Cast<Control>().Concat(extra)) body.Controls.Remove(c);
        boxes.Clear(); extra.Clear();
        bar.Visible = false; detail.Visible = false;
        ok.Visible = false; cancel.Visible = false; back.Visible = false;
        form.AcceptButton = null;
        clicked = null;
        WentBack = false;
    }

    // the last page's text as tall as it needs (the window grows if it and the boxes would reach the buttons);
    // where its boxes go
    static int Fit(int boxCount)
    {
        float scale = text.Width / 512f;                       // (sizes here are the screen's: scaled with its DPI)
        int need = TextRenderer.MeasureText(text.Text, text.Font, new Size(text.Width, int.MaxValue),
                                            TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix).Height + (int)(6 * scale);
        int below = (int)((boxCount * 30 + 20) * scale);       // the boxes, and a gap above the buttons
        int over = text.Top + need + below - ok.Top;
        if (over > 0)
        {
            form.ClientSize = new Size(form.ClientSize.Width, form.ClientSize.Height + over);
            foreach (var b in new[] { ok, cancel, back }) b.Top += over;
        }
        text.Height = need;
        return text.Top + need + (int)(8 * scale);
    }

    static void AddBoxes(IEnumerable<Box> specs, int top)
    {
        foreach (var b in specs ?? new Box[0])
        {
            var c = new CheckBox { Left = 26, Top = top, Width = 510, Height = 26, Text = b.Text, Checked = b.Checked };
            body.Controls.Add(c);
            boxes.Add(c);
            top += 30;
        }
    }

    static string WaitClick()
    {
        form.Activate();
        while (clicked == null) { Pump(); Thread.Sleep(20); }
        return clicked;
    }

    static bool[] States() { return boxes.Select(b => b.Checked).ToArray(); }

    public static bool[] Choices(string message, IList<Box> specs, string okText, bool showBack = false, string folder = null,
                                 Func<string, string> folderCheck = null, int textHeight = 106)
    {
        Clear();
        text.Text = message;
        text.Height = textHeight;          // (taller for a page with more to say)
        int top = textHeight + 26;
        Folder = folder;
        if (folder != null)
        {
            // where it goes: a box with the default, and Browse... to pick another
            var label = new Label { Left = 24, Top = top - 4, Width = 512, Height = 20, Text = "Install in:" };
            folderBox = new TextBox { Left = 26, Top = top + 18, Width = 400, Text = folder };
            var browse = new Button { Left = 434, Top = top + 16, Width = 102, Height = 28, Text = "Browse..." };
            browse.Click += (s, e) =>
            {
                using (var d = new FolderBrowserDialog { Description = "Choose where to install it" })
                    if (d.ShowDialog(form) == DialogResult.OK) folderBox.Text = d.SelectedPath;
            };
            extra.AddRange(new Control[] { label, folderBox, browse });
            body.Controls.AddRange(new Control[] { label, folderBox, browse });
            top += 58;
        }
        AddBoxes(specs, top);
        ok.Text = okText; ok.Visible = true;
        cancel.Visible = true;
        back.Visible = showBack;
        form.AcceptButton = ok;
        if (Unattended) return States();
        while (true)
        {
            string click = WaitClick();
            if (click == "back") { WentBack = true; return null; }
            if (click != "ok") return null;
            if (folder == null) break;
            Folder = folderBox.Text.Trim();
            string problem = folderCheck == null ? null : folderCheck(Folder);
            if (problem == null) break;
            MessageBox.Show(form, problem, form.Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            clicked = null;
        }
        return States();
    }

    public static int Modes(string message, IList<Mode> choices)
    {
        // a page of big buttons: each choice's button, with what it does beside it; Cancel below
        Clear();
        text.Text = message;
        text.Height = 64;
        int top = 90;
        for (int i = 0; i < choices.Count; i++)
        {
            int n = i;
            var b = new Button { Left = 26, Top = top, Width = 180, Height = 44, Text = choices[i].Label,
                                 Font = new Font("Segoe UI Semibold", 10.5f) };
            b.Click += (s, e) => clicked = "mode" + n;
            var note = new Label { UseMnemonic = false, Left = 222, Top = top - 2, Width = 316, Height = 88, Text = choices[i].Note,
                                   ForeColor = Color.FromArgb(80, 80, 90) };
            extra.AddRange(new Control[] { b, note });
            body.Controls.AddRange(new Control[] { b, note });
            if (i == 0) form.AcceptButton = b;
            top += 94;
        }
        cancel.Visible = true;
        if (Unattended) return 0;
        string click = WaitClick();
        return click.StartsWith("mode") ? int.Parse(click.Substring(4)) : -1;
    }

    public static void Progress(string message, double percent, string hint = "")
    {
        if (form == null) return;
        if (ok.Visible || boxes.Count > 0 || extra.Count > 0) Clear();
        text.Text = message;
        text.Height = 30; bar.Top = 58; detail.Top = 86;        // text, bar and hint together
        bar.Visible = true;
        detail.Text = hint; detail.Visible = !string.IsNullOrEmpty(hint);
        target = (int)(Math.Min(100, percent) * 10);
        Pump();
    }

    public static void Hint(string hint)
    {
        if (form == null) return;
        detail.Text = hint; detail.Visible = !string.IsNullOrEmpty(hint);
        Pump();
    }

    public static int Wait(Process p, double upTo, double seconds = 60)
    {
        // while a program runs: keep the window alive and creep the bar towards upTo (never quite reaching it)
        int from = target, goal = (int)(upTo * 10);
        var start = DateTime.Now;
        while (!p.HasExited)
        {
            if (form != null)
            {
                double t = (DateTime.Now - start).TotalSeconds / seconds;
                target = (int)(from + (goal - from) * (1 - Math.Exp(-2 * t)) * 0.95);
                Pump();
            }
            Thread.Sleep(30);
        }
        p.WaitForExit();
        target = Math.Max(target, goal);
        if (form != null) Pump();
        return p.ExitCode;
    }

    // while something else is being waited for (a download, a folder being freed)
    public static void Breathe(int ms = 30)
    {
        if (form != null) Pump();
        Thread.Sleep(ms);
    }

    public static void Creep(double percent) { target = Math.Max(target, (int)(percent * 10)); if (form != null) Pump(); }

    public static bool[] Done(string message, string okText, IList<Box> specs = null)
    {
        if (form == null) return new bool[0];
        Clear();
        target = 1000; bar.Value = 1000;
        text.Text = message;
        AddBoxes(specs, Fit(specs == null ? 0 : specs.Count));
        ok.Text = okText; ok.Visible = true;
        form.AcceptButton = ok;
        if (!Unattended) WaitClick();
        var states = States();
        Close();
        return states;
    }

    public static void Error(string message)
    {
        if (form == null || Unattended)
        {
            if (!Unattended) MessageBox.Show(message, App.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            Close();
            return;
        }
        Clear();
        text.Text = message;
        Fit(0);
        ok.Text = "Close"; ok.Visible = true;
        WaitClick();
        Close();
    }

    // a message over the window (or on its own, without one)
    public static void Say(string message, MessageBoxIcon icon = MessageBoxIcon.Information)
    {
        if (Unattended) return;
        if (form != null) MessageBox.Show(form, message, form.Text, MessageBoxButtons.OK, icon);
        else MessageBox.Show(message, App.Name, MessageBoxButtons.OK, icon);
    }

    public static void Close()
    {
        if (form == null) return;
        closed = true;
        timer.Stop();
        form.Close();
        Pump();
    }
}
