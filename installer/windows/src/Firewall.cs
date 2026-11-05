// Let phones, tablets and Satellites on the home network reach the app (or stop letting them), through Windows
// Firewall's own interface (HNetCfg.FwPolicy2). Reading the rules needs no admin rights; changing them does, so this
// same program is started again with admin rights for that one job (--firewall allow|remove <port> [program]), and
// Windows asks first. A note says so before Windows' prompt. Designed and Created by Project Moon Pi.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Principal;
using Microsoft.Win32;

static class Firewall
{
    const int In = 1, Allow = 1, Block = 0, Tcp = 6, Any = 256, Domain = 1, Private = 2, Public = 4;

    static dynamic Policy() { return Activator.CreateInstance(Type.GetTypeFromProgID("HNetCfg.FwPolicy2")); }

    class Rule { public string Name, Program; public bool Enabled; public int Action, Profiles, Protocol; }

    static List<Rule> Inbound()
    {
        var list = new List<Rule>();
        try
        {
            foreach (dynamic r in Policy().Rules)
            {
                try
                {
                    if ((int)r.Direction != In) continue;
                    list.Add(new Rule { Name = (string)r.Name, Program = (string)r.ApplicationName, Enabled = (bool)r.Enabled,
                                        Action = (int)r.Action, Profiles = (int)r.Profiles, Protocol = (int)r.Protocol });
                }
                catch { }
            }
        }
        catch (Exception e) { App.Log("firewall: couldn't read the rules: " + e.Message); }
        return list;
    }

    class State { public int Ours, Blocks; public bool OursHome, Home, Public; }

    static State Look(string program)
    {
        var rules = Inbound();
        var ours = rules.Where(r => r.Name == App.FirewallRule).ToList();
        var mine = rules.Where(r => !string.IsNullOrEmpty(program) && string.Equals(r.Program, program, StringComparison.OrdinalIgnoreCase) && r.Enabled).ToList();
        var allows = ours.Where(r => r.Enabled)
                         .Concat(mine.Where(r => r.Action == Allow && (r.Protocol == Tcp || r.Protocol == Any))).ToList();
        return new State
        {
            Ours = ours.Count,
            OursHome = ours.Any(r => r.Enabled && r.Action == Allow && (r.Profiles & (Domain | Private)) != 0),
            Blocks = mine.Count(r => r.Action == Block),
            Home = allows.Any(r => (r.Profiles & (Domain | Private)) != 0),
            Public = allows.Any(r => (r.Profiles & Public) != 0),
        };
    }

    // Makes sure phones can connect: "Allowed", "AllowedPublic" (public networks too) or "Declined"
    public static string Ensure(int port, string program, bool quiet)
    {
        var s = Look(program);
        // already fine: our own rule, for home networks, just one of it, and nothing blocking the program. (Another
        // program's or Windows' own "allow this app" rule isn't enough: it can be for other networks, ports or
        // addresses, so phones still time out and Windows was never asked: found on a Windows 10 PC.)
        if (!(s.OursHome && s.Ours == 1 && s.Blocks == 0))
        {
            Elevated("allow", port, program, quiet,
                     "That lets " + App.PhonesWho + " on your home network reach " + App.Name + ". It opens only " +
                     App.Name + "'s port, and only on home (Private) networks.");
            s = Look(program);
        }
        if (!s.OursHome || s.Blocks > 0) return "Declined";
        return s.Public ? "AllowedPublic" : "Allowed";
    }

    // Takes our rule away (Windows asks only if there is one)
    public static void Remove(int port, bool quiet)
    {
        if (Look(null).Ours == 0) return;
        Elevated("remove", port, null, quiet,
                 "That closes the firewall opening " + App.Name + " made for " + App.PhonesShort + ". (If you click No, " +
                 App.Name + " is still removed; only that firewall setting stays.)");
    }

    static bool Elevated(string what, int port, string program, bool quiet, string why)
    {
        string ask = WindowsWillAsk();
        App.Log("firewall " + what + ": Windows' admin question: " + ask);
        if (!quiet && ask != "no")
        {
            string exe = System.IO.Path.GetFileName(App.Exe);
            Ui.Say(ask == "password"
                ? "Next, Windows asks for an administrator's password, to let " + exe + " make changes to this PC. Ask " +
                  "someone with an administrator account on it to type theirs: " + why
                : ask == "yes"
                ? "Next, Windows asks: \"Do you want to allow this app to make changes to your device?\" for " + exe +
                  ".\n\nClick Yes: " + why
                : "If Windows asks \"Do you want to allow this app to make changes to your device?\" for " + exe +
                  ", click Yes: " + why + "\n\n(If it doesn't ask, it's set to allow it without asking: carry on.)");
        }
        try
        {
            var args = new List<string> { "--firewall", what, port.ToString() };
            if (!string.IsNullOrEmpty(program)) args.Add(program);
            var p = Process.Start(new ProcessStartInfo(App.Exe, Proc.Join(args)) { UseShellExecute = true, Verb = "runas" });
            Ui.Wait(p, 89, 60);
            App.Log("firewall " + what + ": exit code " + p.ExitCode);
            return p.ExitCode == 0;
        }
        catch (Win32Exception e)
        {
            App.Log("firewall " + what + ": " + e.Message);      // 1223: the prompt was declined
            return false;
        }
    }

    // run with admin rights: the change itself (exit code 0 if it was made)
    public static int Change(string[] args)
    {
        try
        {
            string what = args[1];
            int port = int.Parse(args[2]);
            string program = args.Length > 3 ? args[3] : null;
            dynamic policy = Policy();
            for (int i = 0; i < 20 && Inbound().Any(r => r.Name == App.FirewallRule); i++) policy.Rules.Remove(App.FirewallRule);
            if (what != "allow") return 0;
            dynamic rule = Activator.CreateInstance(Type.GetTypeFromProgID("HNetCfg.FWRule"));
            rule.Name = App.FirewallRule;
            rule.Description = "Made by the " + App.Name + " installer: lets " + App.PhonesWho + " on your home network reach " + App.Name + ".";
            rule.Protocol = Tcp;
            rule.LocalPorts = port.ToString();
            rule.Direction = In;
            rule.Action = Allow;
            rule.Profiles = Domain | Private;
            rule.Enabled = true;
            policy.Rules.Add(rule);
            if (!string.IsNullOrEmpty(program))
            {
                // Windows adds a Block rule when its "allow this app?" notice is cancelled; a block always beats an allow
                foreach (var name in Inbound().Where(r => r.Action == Block && string.Equals(r.Program, program, StringComparison.OrdinalIgnoreCase))
                                              .Select(r => r.Name).Distinct().ToList())
                    policy.Rules.Remove(name);
            }
            return 0;
        }
        catch (Exception e)
        {
            App.Log("firewall change failed: " + e.Message);
            return 1;
        }
    }

    // Will Windows ask before giving this program admin rights (User Account Control)? "no" (it's set never to ask
    // here, it's off, or this program already has them), "yes" (Yes/No, or Windows' own password check for an
    // admin), "password" (this account isn't an administrator: an administrator's password) or "maybe" (it can't
    // tell). It only reads the setting Windows keeps for it (the "Change User Account Control settings" slider) and
    // this program's own sign-in token: nothing is changed.
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool GetTokenInformation(IntPtr token, int infoClass, out int info, int length, out int returned);

    public static string WindowsWillAsk()
    {
        try
        {
            int type = 0, got;                                                    // TokenElevationType (18)
            GetTokenInformation(WindowsIdentity.GetCurrent().Token, 18, out type, 4, out got);
            if (type == 2) return "no";                                           // already running with admin rights
            int lua = 1, admin = 5, user = 3;
            using (var k = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"))
            {
                if (k != null)
                {
                    lua = Convert.ToInt32(k.GetValue("EnableLUA", 1));
                    admin = Convert.ToInt32(k.GetValue("ConsentPromptBehaviorAdmin", 5));
                    user = Convert.ToInt32(k.GetValue("ConsentPromptBehaviorUser", 3));
                }
            }
            if (lua == 0) return "no";                                            // User Account Control is off
            if (type == 3) return admin == 0 ? "no" : "yes";                      // an administrator (0: never notify)
            if (type == 1)
            {
                // the built-in Administrator account (no split token), or an account that isn't an administrator
                if (new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) return "no";
                return user == 0 ? "maybe" : "password";                         // (0: Windows refuses without asking)
            }
        }
        catch (Exception e) { App.Log("couldn't read the User Account Control setting: " + e.Message); }
        return "maybe";
    }

    // Is this PC on a network Windows calls Public (where it keeps other devices out)?
    public static bool OnPublicNetwork()
    {
        try
        {
            dynamic nlm = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("DCB00C01-570F-4A9B-8D69-199FDBA5723B")));
            foreach (dynamic n in nlm.GetNetworks(1))          // connected networks
                if ((int)n.GetCategory() == 0) return true;     // 0 public, 1 private, 2 domain
        }
        catch (Exception e) { App.Log("network category: " + e.Message); }
        return false;
    }
}
