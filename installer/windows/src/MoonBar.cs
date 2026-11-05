// The installer's progress bar, as the Mac installer's (installer/mac/window.py): the Project Moon Pi patch riding
// its leading edge, and the app's rider on the part already done (App.BarRider):
//   "plane"   a little airliner flying back and forth, turning round at each end (SkyScope, Aviator Trail)
//   "train"   a train with turning wheels and puffs of smoke laying its track and running into the patch, as into a
//             tunnel, then round again (Train Tracker)
// Value runs 0 to Maximum (Ui.cs glides it towards its target). Drawn here, at 30 frames a second; sizes are in the
// window's 96-dpi units, scaled to the screen. Designed and Created by Project Moon Pi.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

class MoonBar : Control
{
    public const int Tall = 72;                         // its height (at 96 dpi)
    const float BarH = 12, Patch = 32;
    public int Maximum = 1000;
    int value;
    public int Value { get { return value; } set { this.value = Math.Max(0, Math.Min(Maximum, value)); } }
    public Image Logo;
    readonly string rider;
    readonly Timer tick = new Timer { Interval = 30 };
    float x;                                            // the rider's place along the done part
    int dir = 1, ticks;
    float turn;                                         // the train's wheels
    readonly List<float[]> puffs = new List<float[]>(); // smoke: x, y, size, age

    public MoonBar(string rider)
    {
        this.rider = rider;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint |
                 ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
        tick.Tick += (s, e) => { if (Visible) { Step(); Invalidate(); } };
        tick.Start();
    }

    protected override void Dispose(bool disposing) { if (disposing) tick.Dispose(); base.Dispose(disposing); }

    float K { get { return Height / (float)Tall; } }
    float W { get { return Width / K; } }           // its width in 96-dpi units
    float Edge { get { return W * value / Maximum; } }
    float BarY { get { return Tall - Patch / 2 - 2; } }

    const float TrainLen = 70, Speed = 1.5f;

    void Step()
    {
        ticks++;
        float edge = Edge;
        if (rider == "train")
        {
            bool running = edge > TrainLen + Patch;
            if (running) { x += Speed; if (x - TrainLen > edge) x = 0; }    // all of it in the tunnel: round again
            else x = 0;
            turn += Speed / 3f;
            float top = BarY - BarH / 2, fx = x - 9;
            if (running && ticks % 9 == 0 && fx < edge - Patch / 2) puffs.Add(new[] { fx, top - 22.5f, 3f, 0f });
            for (int i = puffs.Count - 1; i >= 0; i--)
            {
                var p = puffs[i];
                p[3] += 1; p[0] -= 0.35f; p[1] -= 0.45f; p[2] += 0.26f;
                if (p[3] > 44) puffs.RemoveAt(i);
            }
        }
        else
        {
            float room = edge - Patch / 2 - 26;
            if (room <= 0) { x = 0; dir = 1; }
            else
            {
                x += dir * 1.6f;
                if (x >= room) { x = room; dir = -1; }
                else if (x <= 0) { x = 0; dir = 1; }
            }
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.Clear(BackColor);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.ScaleTransform(K, K);
        float edge = Edge, y0 = BarY - BarH / 2;
        using (var track = new SolidBrush(Color.FromArgb(205, 208, 214))) g.FillRectangle(track, 0, y0, W, BarH);
        if (rider == "train") PaintTrain(g, edge, y0);
        else PaintPlane(g, edge, y0);
        if (Logo != null)
        {
            float px = Math.Min(Math.Max(edge, Patch / 2), W - Patch / 2);
            g.DrawImage(Logo, px - Patch / 2, BarY - Patch / 2, Patch, Patch);
        }
    }

    // an airliner seen from above, nose to the right, 24 units long, centred on (0, 0): the top half (the bottom mirrors it)
    static readonly float[,] Plane = { { 12, 0 }, { 10.5f, -1.6f }, { 2.5f, -1.6f }, { -3, -10 }, { -6, -10 }, { -2, -1.6f },
        { -8, -1.6f }, { -10.5f, -5.5f }, { -12.5f, -5.5f }, { -11, -1.2f }, { -12, 0 } };

    void PaintPlane(Graphics g, float edge, float y0)
    {
        var blue = Color.FromArgb(10, 132, 255);
        using (var b = new SolidBrush(blue)) g.FillRectangle(b, 0, y0, edge, BarH);
        if (edge - Patch / 2 - 26 <= 0) return;
        float cx = x + 12, cy = y0 - 13;
        int n = Plane.GetLength(0);
        var pts = new List<PointF>();
        for (int i = 0; i < n; i++) pts.Add(new PointF(cx + dir * Plane[i, 0], cy + Plane[i, 1]));
        for (int i = n - 2; i >= 1; i--) pts.Add(new PointF(cx + dir * Plane[i, 0], cy - Plane[i, 1]));
        using (var b = new SolidBrush(blue)) g.FillPolygon(b, pts.ToArray());
    }

    void PaintTrain(Graphics g, float edge, float top)
    {
        var dark = Color.FromArgb(11, 122, 71);
        using (var b = new SolidBrush(Color.FromArgb(18, 183, 106))) g.FillRectangle(b, 0, top, edge, BarH);
        using (var p = new Pen(dark, 2))
        {
            g.DrawLine(p, 0, top + 1, edge, top + 1);                         // the rail
            for (float sx = 4; sx < edge; sx += 9) g.DrawLine(p, sx, top + 3, sx, top + BarH - 2);   // sleepers
        }
        // smoke, fading as it rises and spreads behind the train
        foreach (var s in puffs)
            using (var b = new SolidBrush(Color.FromArgb((int)(170 * (1 - s[3] / 44f)), 154, 160, 168)))
                g.FillEllipse(b, s[0] - s[2] / 2, s[1] - s[2] / 2, s[2], s[2]);
        if (edge <= TrainLen + Patch) return;
        // what's past the patch's middle is hidden in the tunnel: drawn only up to it
        var clip = g.Clip;
        g.SetClip(new RectangleF(0, 0, Math.Min(edge, W), Tall));
        var body = Color.FromArgb(46, 107, 230); var cab = Color.FromArgb(29, 63, 145); var coach = Color.FromArgb(59, 130, 246);
        var trim = Color.FromArgb(245, 197, 66); var window = Color.FromArgb(219, 234, 254); var wheel = Color.FromArgb(52, 64, 84);
        float t = top, n = x;
        Action<Color, float, float, float, float> box = (c, l, tp, r, bt) => { using (var b = new SolidBrush(c)) g.FillRectangle(b, n + l, t + tp, r - l, bt - tp); };
        Action<float> wheelAt = cx =>
        {
            float r = 3.2f, cy = t - 3.2f;
            using (var b = new SolidBrush(wheel)) g.FillEllipse(b, n + cx - r, cy - r, 2 * r, 2 * r);
            float dx = (float)((r - 0.6) * Math.Cos(turn)), dy = (float)((r - 0.6) * Math.Sin(turn));
            using (var p = new Pen(Color.White, 1)) g.DrawLine(p, n + cx - dx, cy - dy, n + cx + dx, cy + dy);
        };
        // two coaches, coupled behind the engine
        foreach (float left in new[] { -50f, -72f })
        {
            box(coach, left, -17, left + 19, -6);
            box(cab, left - 0.5f, -18, left + 19.5f, -17);
            box(trim, left, -9, left + 19, -8);
            box(cab, left + 19, -8, left + 22, -6);
            foreach (float wx in new[] { left + 2.5f, left + 7.8f, left + 13 }) box(window, wx, -15, wx + 3.5f, -11);
            wheelAt(left + 4); wheelAt(left + 15);
        }
        // the engine: boiler, cab with a window, funnel, a cow-catcher at the nose, a yellow stripe
        box(body, -24, -15, -5, -6);
        box(cab, -28, -21, -18, -6);
        box(window, -26, -19, -20, -15);
        box(cab, -30, -23, -16, -21);
        box(cab, -11, -21, -7, -15);
        using (var b = new SolidBrush(Color.FromArgb(217, 45, 32)))
            g.FillPolygon(b, new[] { new PointF(n - 5, t - 9), new PointF(n, t - 3), new PointF(n - 5, t - 3) });
        box(trim, -24, -9, -5, -8);
        foreach (float wx in new[] { -22f, -14f, -8f }) wheelAt(wx);
        g.Clip = clip;
    }
}
