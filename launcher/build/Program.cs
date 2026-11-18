// AdvancedRandomizer.exe - the only file a player has to double-click.
//
// It is a bootstrapper, not a second launcher: the window, the decisions and
// all the text live in launcher\start\launcher.ps1 and engine.py next to this
// executable.  This file exists because a double-clicked .cmd flashes a black
// console window, and a .ps1 cannot be double-clicked at all.
//
// Built by .github/workflows/launcher-release.yml with the csc.exe that ships
// inside Windows itself, so the result needs no runtime download: it uses the
// .NET Framework already present on any Windows 10.
//
// All Cyrillic text is written as \u escapes on purpose: the compiler's source
// encoding is then irrelevant, and this file can stay ASCII-only.

using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace AdvancedRandomizer
{
    internal static class Program
    {
        private const string LogFolder = "AdvancedRandomizer";
        private const string LogName = "launcher.log";

        [STAThread]
        private static int Main(string[] args)
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string script = FindScript(baseDir);
            if (script == null)
            {
                Show(
                    "\u041D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D launcher.ps1 \u0440\u044F\u0434\u043E\u043C \u0441 \u044D\u0442\u0438\u043C \u0444\u0430\u0439\u043B\u043E\u043C.\n\n" +
                    "\u0420\u0430\u0441\u043F\u0430\u043A\u0443\u0439\u0442\u0435 \u0430\u0440\u0445\u0438\u0432 \u0446\u0435\u043B\u0438\u043A\u043E\u043C: \u0444\u0430\u0439\u043B\u044B \u043B\u0430\u0443\u043D\u0447\u0435\u0440\u0430 \u043B\u0435\u0436\u0430\u0442 \u0432 \u043F\u0430\u043F\u043A\u0435 launcher\\start.\n\n" +
                    "\u0418\u0441\u043A\u0430\u043B\u0438 \u0437\u0434\u0435\u0441\u044C: " + baseDir);
                return 2;
            }

            string log = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                LogFolder,
                LogName);
            TryDelete(log);

            var start = new ProcessStartInfo
            {
                FileName = PowerShellPath(),
                Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\"",
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = Path.GetDirectoryName(script),
            };

            try
            {
                using (Process process = Process.Start(start))
                {
                    if (process == null)
                    {
                        Show(NoStartMessage(log));
                        return 3;
                    }

                    process.WaitForExit();
                    if (process.ExitCode == 0)
                    {
                        return 0;
                    }

                    Show(
                        "\u041E\u043A\u043D\u043E \u043B\u0430\u0443\u043D\u0447\u0435\u0440\u0430 \u0437\u0430\u043A\u0440\u044B\u043B\u043E\u0441\u044C \u0441 \u043E\u0448\u0438\u0431\u043A\u043E\u0439.\n\n" +
                        Tail(log) + "\n\n" +
                        "\u041F\u043E\u043B\u043D\u044B\u0439 \u043B\u043E\u0433: " + log);
                    return 1;
                }
            }
            catch (Exception error)
            {
                Show(NoStartMessage(log) + "\n\n" + error.Message);
                return 3;
            }
        }

        private static string FindScript(string baseDir)
        {
            string[] candidates =
            {
                Path.Combine(baseDir, "launcher", "start", "launcher.ps1"),
                Path.Combine(baseDir, "start", "launcher.ps1"),
                Path.Combine(baseDir, "launcher.ps1"),
            };
            foreach (string candidate in candidates)
            {
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
            return null;
        }

        private static string PowerShellPath()
        {
            string system = Environment.GetEnvironmentVariable("SystemRoot") ?? @"C:\Windows";
            string full = Path.Combine(system, @"System32\WindowsPowerShell\v1.0\powershell.exe");
            return File.Exists(full) ? full : "powershell.exe";
        }

        private static string NoStartMessage(string log)
        {
            return "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0437\u0430\u043F\u0443\u0441\u0442\u0438\u0442\u044C \u043E\u043A\u043D\u043E \u043B\u0430\u0443\u043D\u0447\u0435\u0440\u0430.\n\n" +
                   "\u041F\u043E\u043F\u0440\u043E\u0431\u0443\u0439\u0442\u0435 \u0437\u0430\u043F\u0443\u0441\u0442\u0438\u0442\u044C AdvancedRandomizer.cmd \u0438\u0437 \u0442\u043E\u0439 \u0436\u0435 \u043F\u0430\u043F\u043A\u0438.\n\n" +
                   "\u041B\u043E\u0433: " + log;
        }

        private static string Tail(string log)
        {
            try
            {
                if (!File.Exists(log))
                {
                    return "(\u0444\u0430\u0439\u043B \u0441 \u043E\u043F\u0438\u0441\u0430\u043D\u0438\u0435\u043C \u043E\u0448\u0438\u0431\u043A\u0438 \u043D\u0435 \u0441\u043E\u0437\u0434\u0430\u043D)";
                }
                string text = File.ReadAllText(log, Encoding.UTF8).Trim();
                if (text.Length == 0)
                {
                    return "(\u043B\u043E\u0433 \u043F\u0443\u0441\u0442)";
                }
                string[] lines = text.Split('\n');
                int from = Math.Max(0, lines.Length - 24);
                return string.Join("\n", lines, from, lines.Length - from).Trim();
            }
            catch (Exception error)
            {
                return "(\u043B\u043E\u0433 \u043D\u0435 \u043F\u0440\u043E\u0447\u0438\u0442\u0430\u0442\u044C: " + error.Message + ")";
            }
        }

        private static void TryDelete(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    File.Delete(path);
                }
            }
            catch (IOException)
            {
            }
        }

        private static void Show(string text)
        {
            MessageBox.Show(
                text,
                "Advanced Randomizer",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
        }
    }
}
