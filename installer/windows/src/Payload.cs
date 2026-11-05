// The one-file download: Install <App>-<version>-for-Windows.exe is the installer with the program's files (a zip)
// added to its end, as NSIS and Inno Setup installers carry theirs. tools/make_downloads.py adds them: the zip, then
// its length (8 bytes, little-endian) and the mark below (16 bytes). When the installer runs, it unpacks them into a
// folder in %TEMP% and installs from there, as from the old downloaded folder; that folder goes when it's done (or,
// if it couldn't be removed, the next time an installer runs). Designed and Created by Project Moon Pi.
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Text;

static class Payload
{
    static readonly byte[] Mark = Encoding.ASCII.GetBytes("MOONPI-PAYLOAD-1");
    static string unpacked;

    static string Prefix { get { return App.Name + " setup "; } }

    // The folder the program's files were unpacked into, or null if this installer carries none (it's run from a
    // folder that has them beside it)
    public static string Unpack()
    {
        Tidy(false);
        long start, length;
        using (var f = new FileStream(App.Exe, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            if (f.Length < 24) return null;
            var tail = new byte[24];
            f.Seek(-24, SeekOrigin.End);
            Read(f, tail, 24);
            for (int i = 0; i < 16; i++) if (tail[8 + i] != Mark[i]) return null;
            length = BitConverter.ToInt64(tail, 0);
            start = f.Length - 24 - length;
            if (length <= 0 || start <= 0) throw new Exception("This installer is damaged: download it again.");
            var zip = new byte[length];
            f.Seek(start, SeekOrigin.Begin);
            Read(f, zip, (int)length);
            string dir = Path.Combine(Path.GetTempPath(), Prefix + Process.GetCurrentProcess().Id);
            Files.TryDeleteDir(dir);
            Directory.CreateDirectory(dir);
            string root = Path.GetFullPath(dir) + Path.DirectorySeparatorChar;
            using (var archive = new ZipArchive(new MemoryStream(zip), ZipArchiveMode.Read))
            {
                foreach (var e in archive.Entries)
                {
                    string to = Path.GetFullPath(Path.Combine(dir, e.FullName.Replace('/', Path.DirectorySeparatorChar)));
                    if (!to.StartsWith(root, StringComparison.OrdinalIgnoreCase)) continue;   // (only inside its folder)
                    if (e.FullName.EndsWith("/")) { Directory.CreateDirectory(to); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(to));
                    using (var src = e.Open())
                    using (var dst = File.Create(to)) src.CopyTo(dst);
                }
            }
            App.Log("unpacked the program (" + (length / 1024) + " KB) into " + dir);
            unpacked = dir;
            AppDomain.CurrentDomain.ProcessExit += (o, a) => Tidy(true);
            return dir;
        }
    }

    static void Read(Stream s, byte[] into, int count)
    {
        int at = 0;
        while (at < count)
        {
            int n = s.Read(into, at, count - at);
            if (n <= 0) throw new Exception("This installer is damaged (it ends early): download it again.");
            at += n;
        }
    }

    // this installer's unpacked files go (mine too: true), and any an earlier one left
    public static void Tidy(bool mine)
    {
        try
        {
            foreach (var d in Directory.GetDirectories(Path.GetTempPath(), Prefix + "*"))
            {
                int pid;
                bool running = false;
                if (int.TryParse(d.Substring(d.LastIndexOf(' ') + 1), out pid) && pid != Process.GetCurrentProcess().Id)
                {
                    try { running = !Process.GetProcessById(pid).HasExited; } catch { }
                }
                if (d == unpacked && !mine) continue;
                if (!running) Files.TryDeleteDir(d);
            }
        }
        catch { }
    }
}
