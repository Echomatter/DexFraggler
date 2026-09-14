using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
internal static class OwnershipProbe
{
    private static string ReadShared(string path)
    {
        using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        using (StreamReader reader = new StreamReader(stream)) return reader.ReadToEnd();
    }
    public static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--launch-child")
        {
            MethodInfo launch = Assembly.LoadFrom(Path.GetFullPath(args[1])).GetType("DexFragglerTray.DetachedRunner").GetMethod("Start", BindingFlags.Public | BindingFlags.Static);
            using (Process child = (Process)launch.Invoke(null, new object[] { args[2], Path.Combine(args[3], "runner", "background.mjs"), args[3], Path.Combine(args[3], ".runtime") }))
                File.WriteAllText(args[4], child.Id.ToString());
            return 0;
        }
        string root = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(args[2])), "ownership-probe-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(root, "runner"));
        Directory.CreateDirectory(Path.Combine(root, ".runtime"));
        string script = Path.Combine(root, "runner", "background.mjs");
        File.WriteAllText(script, "setTimeout(() => { console.log('stdout-after-launcher-exit'); console.error('stderr-after-launcher-exit'); }, 1000); setInterval(() => {}, 1000);", new UTF8Encoding(false));
        string log = Path.Combine(root, ".runtime", "runner.log"), errorLog = Path.Combine(root, ".runtime", "runner-error.log");
        File.WriteAllText(log, "existing-stdout\n"); File.WriteAllText(errorLog, "existing-stderr\n");
        string pidFile = Path.Combine(root, "launched.pid");
        using (Process launcher = Process.Start(new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName, "--launch-child \"" + args[0] + "\" \"" + args[1] + "\" \"" + root + "\" \"" + pidFile + "\"") { UseShellExecute = false, CreateNoWindow = true }))
        { launcher.WaitForExit(); if (launcher.ExitCode != 0) throw new InvalidOperationException("Isolated launcher failed."); }
        Process node = Process.GetProcessById(Int32.Parse(File.ReadAllText(pidFile)));
        try
        {
            MethodInfo method = Assembly.LoadFrom(Path.GetFullPath(args[0])).GetType("DexFragglerTray.Ownership").GetMethod("Worker", BindingFlags.Public | BindingFlags.Static);
            double started = (node.StartTime.ToUniversalTime() - new DateTime(1970, 1, 1)).TotalMilliseconds;
            Dictionary<string, object> status = new Dictionary<string, object> { { "pid", node.Id }, { "root", root }, { "processStartTime", started } };
            bool accepted;
            using (Process owned = (Process)method.Invoke(null, new object[] { root, status })) accepted = owned != null;
            status["processStartTime"] = started + 10000;
            bool stale;
            using (Process wrong = (Process)method.Invoke(null, new object[] { root, status })) stale = wrong == null;
            status["processStartTime"] = started;
            bool other;
            using (Process wrong = (Process)method.Invoke(null, new object[] { Path.Combine(root, "different-project"), status })) other = wrong == null;
            for (int attempt = 0; attempt < 40 && !ReadShared(errorLog).Contains("stderr-after-launcher-exit"); attempt++) System.Threading.Thread.Sleep(100);
            bool stdout = ReadShared(log).Contains("stdout-after-launcher-exit"), stderr = ReadShared(errorLog).Contains("stderr-after-launcher-exit");
            bool appended = ReadShared(log).StartsWith("existing-stdout") && ReadShared(errorLog).StartsWith("existing-stderr");
            var report = new { passed = accepted && stale && other && stdout && stderr && appended, ownedStubAccepted = accepted, staleStartRejected = stale, wrongProjectRejected = other, stdoutAfterLauncherExit = stdout, stderrAfterLauncherExit = stderr, priorLogsPreserved = appended, probeRoot = root, stubOnly = true };
            string json = new JavaScriptSerializer().Serialize(report);
            File.WriteAllText(args[2], json, new UTF8Encoding(false)); Console.WriteLine(json);
            return report.passed ? 0 : 1;
        }
        finally { if (!node.HasExited) { node.Kill(); node.WaitForExit(); } node.Dispose(); }
    }
}
