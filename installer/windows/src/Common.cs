// What the Windows programs share: the log, JSON files, running programs, the app's web address, Windows' folders.
// Designed and Created by Project Moon Pi.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;
using Microsoft.Win32;

static partial class App
{
    public static readonly string LocalAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
    // Project Moon Pi's apps go together under %LOCALAPPDATA%\Programs\Project Moon Pi, where Windows keeps programs
    // installed for one user
    public static readonly string DefaultDir = Path.Combine(LocalAppData, @"Programs\Project Moon Pi\" + Name);
    public static readonly string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + Id;
    public static readonly string LogFile = Path.Combine(Path.GetTempPath(), Name + " install.log");
    public static string Exe { get { return Process.GetCurrentProcess().MainModule.FileName; } }
    public static string Here { get { return Path.GetDirectoryName(Exe); } }

    public static void Log(string text)
    {
        try { File.AppendAllText(LogFile, DateTime.Now.ToString("HH:mm:ss") + " " + text + "\r\n", Encoding.UTF8); } catch { }
    }

    // the uninstaller runs from a copy in %TEMP% (it can't remove the folder it's running from), and that copy can't
    // remove itself: the next install or uninstall tidies away earlier ones
    public static void TidyTemp()
    {
        int me = Process.GetCurrentProcess().Id;
        try
        {
            foreach (var d in Directory.GetDirectories(Path.GetTempPath(), Name + " uninstall *"))
                if (!d.EndsWith(" " + me)) { try { Directory.Delete(d, true); } catch { } }
        }
        catch { }
    }

    public static void LogHeader(string what)
    {
        TidyTemp();
        try { File.AppendAllText(LogFile, "== " + DateTime.Now + " " + Name + " " + what + "\r\n", Encoding.UTF8); } catch { }
    }

    // The folder it's installed in now, if anywhere (Settings > Apps knows), so an update goes to the same place
    public static string InstalledDir()
    {
        string at = null;
        using (var k = Registry.CurrentUser.OpenSubKey(UninstallKey)) { if (k != null) at = k.GetValue("InstallLocation") as string; }
        if (!string.IsNullOrEmpty(at) && File.Exists(Path.Combine(at, InfoFile))) return at.TrimEnd('\\');
        foreach (var before in OldDirs)                            // (where earlier versions installed it)
            if (File.Exists(Path.Combine(before, InfoFile))) return before;
        return null;
    }

    public static string InstalledVersion(string dir)
    {
        using (var k = Registry.CurrentUser.OpenSubKey(UninstallKey))
        {
            var v = k == null ? null : k.GetValue("DisplayVersion") as string;
            if (!string.IsNullOrEmpty(v)) return v;
        }
        var j = InstallInfo(dir);
        return j != null && j.ContainsKey("version") ? Convert.ToString(j["version"]) : null;
    }

    public static Dictionary<string, object> InstallInfo(string dir) { return Json.Read(Path.Combine(dir, InfoFile)); }
    public static bool IsInstalledIn(string dir) { return File.Exists(Path.Combine(dir, InfoFile)); }
    public static string AppLog(string dir) { return Path.Combine(dir, Slug + ".log"); }

    public static int InstalledPort(string dir)
    {
        var j = InstallInfo(dir);
        try { if (j != null && j.ContainsKey("port")) return Convert.ToInt32(j["port"]); } catch { }
        return DefaultPort;
    }

    public static bool InstalledFlag(string dir, string key, bool otherwise)
    {
        var j = InstallInfo(dir);
        try { if (j != null && j.ContainsKey(key) && j[key] != null) return Convert.ToBoolean(j[key]); } catch { }
        return otherwise;
    }

    // Is version a newer than b? (1 newer, 0 the same, -1 older)
    public static int Newer(string a, string b)
    {
        try { return new Version(a).CompareTo(new Version(b)); } catch { return string.Compare(a, b, StringComparison.Ordinal); }
    }
}

static class Json
{
    public static Dictionary<string, object> Read(string path)
    {
        try
        {
            string text = File.ReadAllText(path, Encoding.UTF8).TrimStart('﻿');
            return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(text);
        }
        catch { return null; }
    }

    public static void Write(string path, Dictionary<string, object> data)
    {
        File.WriteAllText(path, new JavaScriptSerializer().Serialize(data), new UTF8Encoding(false));
    }
}

static class Proc
{
    // one argument as Windows programs read it back (quotes and backslashes escaped)
    public static string Quote(string a)
    {
        if (a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return a;
        var sb = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in a)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { sb.Append('\\', slashes * 2 + 1); sb.Append('"'); }
            else { sb.Append('\\', slashes); sb.Append(c); }
            slashes = 0;
        }
        sb.Append('\\', slashes * 2);
        return sb.Append('"').ToString();
    }

    public static string Join(IEnumerable<string> args) { return string.Join(" ", args.Select(Quote)); }

    // a program run hidden, its output collected (for the log)
    public static Process StartHidden(string exe, IEnumerable<string> args, string dir, StringBuilder output)
    {
        var si = new ProcessStartInfo(exe, Join(args))
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = output != null, RedirectStandardError = output != null,
            WorkingDirectory = dir ?? Path.GetTempPath(),
        };
        if (output != null)
        {
            si.StandardOutputEncoding = si.StandardErrorEncoding = Encoding.UTF8;
            si.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        }
        var p = new Process { StartInfo = si };
        if (output != null)
        {
            DataReceivedEventHandler take = (s, e) => { if (e.Data != null) lock (output) output.AppendLine(e.Data); };
            p.OutputDataReceived += take;
            p.ErrorDataReceived += take;
        }
        p.Start();
        if (output != null) { p.BeginOutputReadLine(); p.BeginErrorReadLine(); }
        return p;
    }

    // run it and wait (for quick checks): its exit code, or -1 if it couldn't start
    public static int Quick(string exe, IEnumerable<string> args, int seconds = 30, string dir = null, StringBuilder output = null)
    {
        try
        {
            var p = StartHidden(exe, args, dir, output ?? new StringBuilder());
            if (!p.WaitForExit(seconds * 1000)) { try { p.Kill(); } catch { } return -1; }
            p.WaitForExit();
            return p.ExitCode;
        }
        catch { return -1; }
    }

    public static void Open(string url)
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); } catch { }
    }

    // the folder of a running program (null if Windows won't say, as for another user's)
    public static string PathOf(Process p)
    {
        try
        {
            var sb = new StringBuilder(1024);
            int size = sb.Capacity;
            IntPtr h = OpenProcess(0x1000, false, p.Id);   // PROCESS_QUERY_LIMITED_INFORMATION
            if (h == IntPtr.Zero) return null;
            try { return QueryFullProcessImageName(h, 0, sb, ref size) ? sb.ToString() : null; }
            finally { CloseHandle(h); }
        }
        catch { return null; }
    }

    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(int access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool QueryFullProcessImageName(IntPtr h, int flags, StringBuilder name, ref int size);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
}

static class Web
{
    static Web()
    {
        ServicePointManager.SecurityProtocol |= (SecurityProtocolType)3072;    // TLS 1.2
    }

    // is the app answering on this computer?
    public static bool Up(int port, int ms = 2000)
    {
        try
        {
            var r = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + App.ProbePath);
            r.Timeout = ms; r.ReadWriteTimeout = ms; r.Proxy = null;
            using (r.GetResponse()) return true;
        }
        catch (WebException e) { return e.Response != null; }   // (an error page is still an answer)
        catch { return false; }
    }

    // the app's own shutdown request (only from this computer, with its header), if it has one
    public static bool AskToStop(int port)
    {
        if (App.StopHeader == null) return false;
        try
        {
            var r = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + "/api/shutdown");
            r.Method = "POST"; r.Timeout = 3000; r.Proxy = null; r.ContentLength = 0;
            r.Headers[App.StopHeader] = "stop";
            using (r.GetResponse()) return true;
        }
        catch { return false; }
    }

    // can it reach the internet (python.org, pypi.org)?
    public static bool Online()
    {
        foreach (var url in new[] { "https://pypi.org/simple/pip/", "https://www.python.org/" })
        {
            try
            {
                var r = (HttpWebRequest)WebRequest.Create(url);
                r.Method = "HEAD"; r.Timeout = 10000;
                using (r.GetResponse()) return true;
            }
            catch (Exception e) { App.Log("no answer from " + url + ": " + e.Message); }
        }
        return false;
    }
}

static class Files
{
    // drop the "downloaded from the internet" mark (Windows keeps it beside the file, as name:Zone.Identifier)
    public static void Unblock(string dir)
    {
        foreach (var f in Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories))
        {
            try { DeleteFile(f + ":Zone.Identifier"); } catch { }
        }
    }

    public static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
    }

    public static void TryDeleteDir(string path)
    {
        try { if (Directory.Exists(path)) Directory.Delete(path, true); } catch { }
    }

    public static void CopyDir(string from, string to)
    {
        Directory.CreateDirectory(to);
        foreach (var f in Directory.GetFiles(from)) File.Copy(f, Path.Combine(to, Path.GetFileName(f)), true);
        foreach (var d in Directory.GetDirectories(from)) CopyDir(d, Path.Combine(to, Path.GetFileName(d)));
    }

    public static long SizeOf(string dir)
    {
        try { return Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories).Sum(f => new FileInfo(f).Length); }
        catch { return 0; }
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool DeleteFile(string name);
}
