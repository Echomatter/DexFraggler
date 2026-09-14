using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Management;
using System.Net;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace DexFragglerTray
{
    internal static class Data
    {
        public static JavaScriptSerializer Serializer()
        {
            return new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024, RecursionLimit = 160 };
        }
        public static Dictionary<string, object> Read(string path)
        {
            try { return Serializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path)) ?? new Dictionary<string, object>(); }
            catch { return new Dictionary<string, object>(); }
        }
        public static string Text(IDictionary<string, object> d, string key, string fallback = "")
        {
            object value;
            return d != null && d.TryGetValue(key, out value) && value != null ? Convert.ToString(value) : fallback;
        }
        public static bool Bool(IDictionary<string, object> d, string key, bool fallback = false)
        {
            object value;
            if (d == null || !d.TryGetValue(key, out value) || value == null) return fallback;
            bool parsed;
            if (Boolean.TryParse(Convert.ToString(value), out parsed)) return parsed;
            return Convert.ToString(value) == "1";
        }
        public static double Number(IDictionary<string, object> d, string key, double fallback = 0)
        {
            double result;
            return Double.TryParse(Text(d, key), out result) && !Double.IsInfinity(result) && !Double.IsNaN(result) ? result : fallback;
        }
        public static long Now { get { return (long)(DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalMilliseconds; } }
        public static double Timestamp(IDictionary<string, object> d, string key)
        {
            string value = Text(d, key);
            double number;
            if (Double.TryParse(value, out number)) return number < 100000000000 ? number * 1000 : number;
            DateTime date;
            if (DateTime.TryParse(value, null, System.Globalization.DateTimeStyles.RoundtripKind, out date))
                return (date.ToUniversalTime() - new DateTime(1970, 1, 1)).TotalMilliseconds;
            return 0;
        }
        public static void AtomicText(string path, string text)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temporary = path + "." + Process.GetCurrentProcess().Id + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temporary, text, new UTF8Encoding(false));
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else
                {
                    try { File.Move(temporary, path); }
                    catch (IOException) { if (File.Exists(path)) File.Replace(temporary, path, null); else throw; }
                }
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        public static void AtomicJson(string path, object data) { AtomicText(path, Serializer().Serialize(data)); }
        public static string Canonical(string path) { return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar); }
        public static bool SamePath(string a, string b)
        {
            try { return String.Equals(Canonical(a), Canonical(b), StringComparison.OrdinalIgnoreCase); }
            catch { return false; }
        }
    }

    internal static class Art
    {
        [DllImport("user32.dll", CharSet = CharSet.Auto)] private static extern bool DestroyIcon(IntPtr handle);
        public static Icon CreateIcon()
        {
            using (Bitmap bitmap = new Bitmap(64, 64))
            using (Graphics g = Graphics.FromImage(bitmap))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                using (SolidBrush bg = new SolidBrush(Color.FromArgb(25, 37, 29))) g.FillEllipse(bg, 2, 2, 60, 60);
                using (Pen border = new Pen(Color.FromArgb(117, 149, 93), 3)) g.DrawEllipse(border, 4, 4, 56, 56);
                PointF[] wave = new PointF[49];
                for (int i = 0; i < wave.Length; i++) wave[i] = new PointF(9 + i * 46f / 48, 32 - (float)Math.Sin(i * Math.PI * 3 / 48) * 14);
                using (Pen pen = new Pen(Color.FromArgb(237, 186, 111), 5)) { pen.StartCap = LineCap.Round; pen.EndCap = LineCap.Round; g.DrawLines(pen, wave); }
                IntPtr handle = bitmap.GetHicon();
                try { using (Icon borrowed = Icon.FromHandle(handle)) return (Icon)borrowed.Clone(); }
                finally { DestroyIcon(handle); }
            }
        }
    }

    internal static class Ownership
    {
        private static double Start(Process process)
        {
            return (process.StartTime.ToUniversalTime() - new DateTime(1970, 1, 1)).TotalMilliseconds;
        }
        public static double StartTime(Process process) { return Start(process); }
        private static string CommandLine(int pid)
        {
            try
            {
                using (ManagementObjectSearcher search = new ManagementObjectSearcher("SELECT CommandLine FROM Win32_Process WHERE ProcessId=" + pid))
                using (ManagementObjectCollection results = search.Get())
                    foreach (ManagementObject row in results) using (row) { return Convert.ToString(row["CommandLine"]); }
            }
            catch { }
            return "";
        }
        private static int ParentPid(int pid)
        {
            try
            {
                using (ManagementObjectSearcher search = new ManagementObjectSearcher("SELECT ParentProcessId FROM Win32_Process WHERE ProcessId=" + pid))
                using (ManagementObjectCollection results = search.Get())
                    foreach (ManagementObject row in results) using (row) { return Convert.ToInt32(row["ParentProcessId"]); }
            }
            catch { }
            return -1;
        }
        public static Process Worker(string root, IDictionary<string, object> status)
        {
            Process process = null;
            try
            {
                int pid = (int)Data.Number(status, "pid");
                if (pid <= 0) return null;
                process = Process.GetProcessById(pid);
                if (process.HasExited || !String.Equals(process.ProcessName, "node", StringComparison.OrdinalIgnoreCase)) { process.Dispose(); return null; }
                string recordedRoot = Data.Text(status, "root");
                if (recordedRoot.Length > 0 && !Data.SamePath(root, recordedRoot)) { process.Dispose(); return null; }
                string script = Path.Combine(root, "runner", "background.mjs").Replace('/', '\\');
                string command = CommandLine(pid).Replace('/', '\\');
                bool absoluteScript = command.IndexOf(script, StringComparison.OrdinalIgnoreCase) >= 0;
                double started = Data.Timestamp(status, "processStartTime");
                bool exactStart = started > 0 && Math.Abs(Start(process) - started) <= 2000;
                bool relativeScript = command.IndexOf("runner\\background.mjs", StringComparison.OrdinalIgnoreCase) >= 0;
                // An absolute script establishes project ownership. Relative launchers additionally
                // need the exact process start recorded in this project's status/launch receipt.
                if (!(absoluteScript || (exactStart && relativeScript)) || (started > 0 && !exactStart)) { process.Dispose(); return null; }
                return process;
            }
            catch { if (process != null) process.Dispose(); return null; }
        }
        public static Process Native(string root, IDictionary<string, object> status, Process worker)
        {
            Process process = null;
            try
            {
                int pid = (int)Data.Number(status, "nativePid");
                if (pid <= 0 || worker == null) return null;
                process = Process.GetProcessById(pid);
                string expected = Path.Combine(root, "native", "bin", "DexfragglerReference.exe");
                if (process.HasExited || !Data.SamePath(process.MainModule.FileName, expected) || ParentPid(pid) != worker.Id) { process.Dispose(); return null; }
                double started = Data.Timestamp(status, "nativeProcessStartTime");
                if (started > 0 && Math.Abs(Start(process) - started) > 2000) { process.Dispose(); return null; }
                return process;
            }
            catch { if (process != null) process.Dispose(); return null; }
        }
        public static Process Discover(string root)
        {
            // This fallback intentionally accepts only an absolute script path. It never guesses
            // ownership from the common node.exe process name or a stale pid file alone.
            foreach (Process candidate in Process.GetProcessesByName("node"))
            {
                int pid;
                try { pid = candidate.Id; } catch { candidate.Dispose(); continue; }
                candidate.Dispose();
                Process owned = Worker(root, new Dictionary<string, object> { { "pid", pid } });
                if (owned != null) return owned;
            }
            return null;
        }
    }

    internal static class DetachedRunner
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct SecurityAttributes { public int Length; public IntPtr Descriptor; public int Inherit; }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct StartupInfo
        {
            public int Size; public string Reserved; public string Desktop; public string Title;
            public int X; public int Y; public int XSize; public int YSize; public int XChars; public int YChars;
            public int Fill; public int Flags; public short Show; public short ReservedBytes; public IntPtr ReservedData;
            public IntPtr Input; public IntPtr Output; public IntPtr Error;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct ProcessInfo { public IntPtr Process; public IntPtr Thread; public int Pid; public int ThreadId; }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateFile(string path, uint access, uint sharing, ref SecurityAttributes security, uint creation, uint attributes, IntPtr template);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CreateProcess(string application, StringBuilder command, IntPtr processSecurity, IntPtr threadSecurity, bool inheritHandles, uint flags, IntPtr environment, string directory, ref StartupInfo startup, out ProcessInfo information);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);
        private static readonly IntPtr InvalidHandle = new IntPtr(-1);
        private static IntPtr FileHandle(string path, uint access, uint creation, ref SecurityAttributes security)
        {
            IntPtr handle = CreateFile(path, access, 3, ref security, creation, 0x80, IntPtr.Zero);
            if (handle == InvalidHandle) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            return handle;
        }
        private static void Close(IntPtr handle) { if (handle != IntPtr.Zero && handle != InvalidHandle) CloseHandle(handle); }
        public static Process Start(string node, string script, string root, string runtime)
        {
            Directory.CreateDirectory(runtime);
            SecurityAttributes security = new SecurityAttributes { Length = Marshal.SizeOf(typeof(SecurityAttributes)), Inherit = 1 };
            IntPtr input = IntPtr.Zero, output = IntPtr.Zero, error = IntPtr.Zero;
            ProcessInfo child = new ProcessInfo();
            try
            {
                // Direct inherited file handles keep logging after this tray process exits.
                input = FileHandle("NUL", 0x80000000, 3, ref security);
                output = FileHandle(Path.Combine(runtime, "runner.log"), 4, 4, ref security);
                error = FileHandle(Path.Combine(runtime, "runner-error.log"), 4, 4, ref security);
                StartupInfo startup = new StartupInfo { Size = Marshal.SizeOf(typeof(StartupInfo)), Flags = 0x101, Show = 0, Input = input, Output = output, Error = error };
                StringBuilder command = new StringBuilder("\"" + node + "\" \"" + script + "\"");
                if (!CreateProcess(node, command, IntPtr.Zero, IntPtr.Zero, true, 0x08000000, IntPtr.Zero, root, ref startup, out child))
                    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                return Process.GetProcessById(child.Pid);
            }
            finally { Close(input); Close(output); Close(error); Close(child.Thread); Close(child.Process); }
        }
    }

    internal static class TableExport
    {
        private const string TargetVersion = "ideal-waveform-v1";
        private static readonly string[] Shapes = { "sine", "triangle", "square", "saw" };
        private static Dictionary<string, object> Object(object value)
        {
            Dictionary<string, object> result = value as Dictionary<string, object>;
            if (result == null) throw new FormatException();
            return result;
        }
        private static object Field(Dictionary<string, object> value, string key)
        {
            object result;
            if (!value.TryGetValue(key, out result)) throw new FormatException();
            return result;
        }
        private static object[] Array(object value)
        {
            object[] result = value as object[];
            if (result == null) throw new FormatException();
            return result;
        }
        private static double Number(object value)
        {
            if (!(value is int || value is long || value is double || value is decimal)) throw new FormatException();
            double result = Convert.ToDouble(value);
            if (Double.IsNaN(result) || Double.IsInfinity(result)) throw new FormatException();
            return result;
        }
        private static void Keys(Dictionary<string, object> value, params string[] keys)
        {
            if (value.Count != keys.Length || keys.Any(key => !value.ContainsKey(key))) throw new FormatException();
        }
        public static void Validate(object value)
        {
            Dictionary<string, object> table = Object(value);
            if (!System.Object.Equals(Field(table, "format"), "dexfraggler-table") || Number(Field(table, "version")) != 4
                || !System.Object.Equals(Field(table, "targetVersion"), TargetVersion)) throw new FormatException();
            Dictionary<string, object> config = Object(Field(table, "config"));
            Keys(config, "allowDetune", "anchors");
            if (!(Field(config, "allowDetune") is bool)) throw new FormatException();
            object[] anchors = Array(Field(config, "anchors"));
            if (anchors.Length < 1 || anchors.Length > 32) throw new FormatException();
            double previous = -1;
            foreach (object item in anchors)
            {
                Dictionary<string, object> anchor = Object(item); Keys(anchor, "slot", "shape");
                double slot = Number(Field(anchor, "slot"));
                if (slot < 0 || slot > 31 || slot != Math.Floor(slot) || slot <= previous || !Shapes.Contains(Field(anchor, "shape") as string)) throw new FormatException();
                previous = slot;
            }
            object[] targets = Array(Field(table, "targets"));
            if (targets.Length != 32) throw new FormatException();
            foreach (object item in targets)
            {
                Dictionary<string, object> target = Object(item); Keys(target, "kind", "weights");
                if (!System.Object.Equals(Field(target, "kind"), TargetVersion)) throw new FormatException();
                object[] weights = Array(Field(target, "weights"));
                if (weights.Length != 4) throw new FormatException();
                double sum = 0;
                foreach (object weight in weights) { double n = Number(weight); if (n < 0) throw new FormatException(); sum += n; }
                if (Math.Abs(sum - 1) > 1e-12) throw new FormatException();
            }
            object[] cells = Array(Field(table, "cells"));
            if (cells.Length > 1024) throw new FormatException();
        }
    }

    internal sealed class Remote
    {
        private readonly string root;
        public Remote(string root) { this.root = root; }
        private Dictionary<string, object> Config()
        {
            Dictionary<string, object> config = Data.Read(Path.Combine(root, ".runtime", "runner-config.json"));
            if (Data.Text(config, "url").Length == 0) throw new InvalidOperationException("Runner configuration is missing. Configure this project's site first.");
            return config;
        }
        public Uri Site()
        {
            Uri value;
            if (!Uri.TryCreate(Data.Text(Config(), "url"), UriKind.Absolute, out value) || (value.Scheme != "https" && value.Scheme != "http"))
                throw new InvalidOperationException("The configured site address must use HTTP or HTTPS.");
            return value;
        }
        private HttpClient Client()
        {
            Dictionary<string, object> config = Config();
            string secret = Data.Text(config, "secret"), bypass = Data.Text(config, "bypass");
            if (secret.Length == 0) throw new InvalidOperationException("The runner authorization has not been configured.");
            HttpClient client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false, UseCookies = false });
            client.Timeout = TimeSpan.FromSeconds(25);
            client.DefaultRequestHeaders.Add("x-dexfraggler-worker", secret);
            if (bypass.Length > 0) client.DefaultRequestHeaders.Add("OAI-Sites-Authorization", "Bearer " + bypass);
            string cookie = Data.Text(config, "cookie");
            if (cookie.Length > 0) client.DefaultRequestHeaders.Add("Cookie", cookie);
            return client;
        }
        private Uri Endpoint(string query) { return new Uri(Site().AbsoluteUri.TrimEnd('/') + "/api/table" + query); }
        public async Task Running(bool running)
        {
            using (HttpClient client = Client())
            using (StringContent body = new StringContent(Data.Serializer().Serialize(new { action = "running", running = running }), Encoding.UTF8, "application/json"))
            using (HttpResponseMessage response = await client.PostAsync(Endpoint(""), body).ConfigureAwait(false))
            {
                if (!response.IsSuccessStatusCode) throw new InvalidOperationException("The site could not synchronize pause/resume (HTTP " + (int)response.StatusCode + "). The local control is saved.");
            }
        }
        public async Task<string> Export()
        {
            using (HttpClient client = Client())
            using (HttpResponseMessage response = await client.GetAsync(Endpoint("?export=1")).ConfigureAwait(false))
            {
                if (!response.IsSuccessStatusCode) throw new InvalidOperationException("The table download failed (HTTP " + (int)response.StatusCode + ").");
                string text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                if (text.Length > 32 * 1024 * 1024) throw new InvalidOperationException("The table response exceeds 32 MB.");
                try
                {
                    TableExport.Validate(Data.Serializer().DeserializeObject(text));
                }
                catch { throw new InvalidOperationException("The site did not return a version 4 formula table. No export was saved."); }
                return text;
            }
        }
    }

    internal sealed class TrayContext : ApplicationContext
    {
        private readonly string root, runtime, controlPath, statusPath;
        private readonly bool selfTest;
        private readonly Remote remote;
        private readonly NotifyIcon tray;
        private readonly Icon icon;
        private readonly ContextMenuStrip menu;
        private readonly ToolStripMenuItem pause, phase, counts, priority, download;
        private readonly System.Windows.Forms.Timer timer;
        private readonly Dictionary<string, ToolStripMenuItem> priorityItems = new Dictionary<string, ToolStripMenuItem>();
        private Dictionary<string, object> status = new Dictionary<string, object>();
        private Dictionary<string, object> control = new Dictionary<string, object>();
        private bool exiting, toggling, downloading;
        private long lastLaunchAttempt;
        private string priorityApplied = "";
        public static readonly string[] Priorities = { "Idle", "BelowNormal", "Normal", "AboveNormal", "High" };
        public int MenuCount { get { return menu.Items.Count; } }
        public int PriorityCount { get { return priorityItems.Count; } }

        private void WriteTrayStatus(bool initialized)
        {
            if (selfTest) return;
            try
            {
                using (Process process = Process.GetCurrentProcess())
                    Data.AtomicJson(Path.Combine(runtime, "tray-status.json"), new Dictionary<string, object>
                    {
                        { "pid", process.Id }, { "processStartTime", Ownership.StartTime(process) },
                        { "executable", process.MainModule.FileName }, { "root", root },
                        { "notifyIconInitialized", initialized }, { "notifyIconVisible", initialized && tray.Visible },
                        { "menuItems", MenuCount }, { "priorityChoices", PriorityCount },
                        { "localPaused", Data.Bool(control, "paused", Data.Bool(status, "localPaused")) },
                        { "priority", DesiredPriority() }, { "updatedAt", Data.Now }
                    });
            }
            catch { }
        }

        public TrayContext(string root, bool selfTest)
        {
            this.root = Data.Canonical(root); this.selfTest = selfTest;
            runtime = Path.Combine(this.root, ".runtime"); Directory.CreateDirectory(runtime);
            controlPath = Path.Combine(runtime, "runner-control.json"); statusPath = Path.Combine(runtime, "runner-status.json");
            remote = new Remote(this.root); icon = Art.CreateIcon(); menu = new ContextMenuStrip();
            ToolStripMenuItem open = new ToolStripMenuItem("Open waveform table", null, delegate { OpenTable(); });
            open.Font = new Font(open.Font, FontStyle.Bold); menu.Items.Add(open); menu.Items.Add(new ToolStripSeparator());
            phase = new ToolStripMenuItem("Connecting to runner…") { Enabled = false }; menu.Items.Add(phase);
            counts = new ToolStripMenuItem("Saved experiments") { Enabled = false }; menu.Items.Add(counts);
            pause = new ToolStripMenuItem("Pause computing", null, async delegate { await Toggle(); }); menu.Items.Add(pause);
            priority = new ToolStripMenuItem("Process priority"); menu.Items.Add(priority);
            foreach (string name in Priorities)
            {
                string value = name;
                ToolStripMenuItem item = new ToolStripMenuItem(name, null, delegate { ChangePriority(value); }) { CheckOnClick = false };
                priority.DropDownItems.Add(item); priorityItems.Add(name, item);
            }
            download = new ToolStripMenuItem("Download table results…", null, async delegate { await Download(); }); menu.Items.Add(download);
            menu.Items.Add(new ToolStripSeparator()); menu.Items.Add(new ToolStripMenuItem("Exit tray and pause locally", null, delegate { ExitPaused(); }));
            tray = new NotifyIcon { Icon = icon, Text = "DexFraggler", ContextMenuStrip = menu, Visible = !selfTest };
            tray.DoubleClick += delegate { OpenTable(); };
            menu.Opening += delegate { RefreshState(); };
            timer = new System.Windows.Forms.Timer { Interval = 2000 };
            timer.Tick += delegate { RefreshState(); };
            RefreshState();
            if (!selfTest) timer.Start();
        }
        private bool IsPaused()
        {
            return Data.Bool(control, "paused", Data.Bool(status, "localPaused")) || (status.ContainsKey("running") && !Data.Bool(status, "running"));
        }
        private string DesiredPriority()
        {
            string value = Data.Text(control, "priority", Data.Text(status, "priority", "BelowNormal"));
            return Priorities.Contains(value) ? value : "BelowNormal";
        }
        private void Show(string message, bool warning = false)
        {
            if (!selfTest && !exiting) tray.ShowBalloonTip(5000, "DexFraggler", message, warning ? ToolTipIcon.Warning : ToolTipIcon.Info);
        }
        public void WriteControl(bool paused, string processPriority)
        {
            if (!Priorities.Contains(processPriority)) throw new ArgumentException("Unsupported process priority.");
            Dictionary<string, object> next = Data.Read(controlPath);
            next["paused"] = paused; next["priority"] = processPriority; next["updatedAt"] = Data.Now;
            Data.AtomicJson(controlPath, next); control = next;
        }
        private void RefreshState()
        {
            if (exiting) return;
            try
            {
                status = Data.Read(statusPath); control = Data.Read(controlPath);
                bool paused = IsPaused(); pause.Text = paused ? "Resume computing" : "Pause computing"; pause.Enabled = !toggling;
                string requested = DesiredPriority(); foreach (KeyValuePair<string, ToolStripMenuItem> item in priorityItems) item.Value.Checked = item.Key == requested;
                string state = Data.Text(status, "phase", "Waiting for runner status");
                double lastSeen = Data.Timestamp(status, "updatedAt");
                if (lastSeen > 0 && Data.Now - lastSeen > 60000) state = "Runner status is stale";
                if (paused) state = "Paused · " + state;
                phase.Text = state.Length > 110 ? state.Substring(0, 107) + "…" : state;
                double evaluated = Data.Number(status, "evaluations");
                counts.Text = evaluated.ToString("N0") + " evaluations · " + requested + " priority";
                tray.Text = ("DexFraggler · " + (paused ? "Paused" : "Running")).Substring(0, Math.Min(63, ("DexFraggler · " + (paused ? "Paused" : "Running")).Length));
                if (!selfTest) { EnsureRunner(); ApplyPriority(false); WriteTrayStatus(true); }
            }
            catch { phase.Text = "Cannot read local runner status"; }
        }
        private void OpenTable()
        {
            try { Process.Start(new ProcessStartInfo(remote.Site().AbsoluteUri) { UseShellExecute = true }); }
            catch { Show("The site could not be opened. Check this project's runner configuration and default browser.", true); }
        }
        private Process OwnedWorker()
        {
            Process process = Ownership.Worker(root, status);
            if (process == null) process = Ownership.Worker(root, Data.Read(Path.Combine(runtime, "tray-runner-launch.json")));
            return process;
        }
        private static string NodePath()
        {
            foreach (string part in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
            {
                try { string path = Path.Combine(Environment.ExpandEnvironmentVariables(part.Trim().Trim('"')), "node.exe"); if (File.Exists(path)) return Path.GetFullPath(path); }
                catch { }
            }
            throw new FileNotFoundException("Node.js was not found on PATH.");
        }
        private void EnsureRunner()
        {
            using (Process owned = OwnedWorker()) { if (owned != null) return; }
            if (Data.Now - lastLaunchAttempt < 30000) return;
            lastLaunchAttempt = Data.Now;
            using (Process found = Ownership.Discover(root))
            {
                if (found != null) { RecordLaunch(found); return; }
            }
            try
            {
                string script = Path.Combine(root, "runner", "background.mjs");
                if (!File.Exists(script)) throw new FileNotFoundException("The project's runner/background.mjs is missing.");
                if (!File.Exists(Path.Combine(runtime, "runner-config.json"))) throw new FileNotFoundException("Configure the project's runner before starting it.");
                using (Process process = DetachedRunner.Start(NodePath(), script, root, runtime))
                {
                    RecordLaunch(process);
                    try { process.PriorityClass = (ProcessPriorityClass)Enum.Parse(typeof(ProcessPriorityClass), DesiredPriority()); } catch { }
                }
                phase.Text = "Starting the background runner…";
            }
            catch (FileNotFoundException e) { Show(e.Message, true); }
            catch { Show("The background runner could not start. Check Node.js and the local project configuration.", true); }
        }
        private void RecordLaunch(Process process)
        {
            Data.AtomicJson(Path.Combine(runtime, "tray-runner-launch.json"), new Dictionary<string, object>
            { { "pid", process.Id }, { "processStartTime", Ownership.StartTime(process) }, { "root", root }, { "updatedAt", Data.Now } });
            Data.AtomicText(Path.Combine(runtime, "runner.pid"), process.Id.ToString());
        }
        private void ApplyPriority(bool notify)
        {
            string wanted = DesiredPriority();
            using (Process worker = OwnedWorker())
            {
                if (worker == null) return;
                using (Process native = Ownership.Native(root, status, worker))
                {
                    string signature = worker.Id + ":" + (native == null ? 0 : native.Id) + ":" + wanted;
                    if (signature == priorityApplied) return;
                    try
                    {
                        ProcessPriorityClass value = (ProcessPriorityClass)Enum.Parse(typeof(ProcessPriorityClass), wanted);
                        worker.PriorityClass = value;
                        if (native != null) native.PriorityClass = value;
                        priorityApplied = signature;
                        if (notify) Show("Process priority set to " + wanted + ".");
                    }
                    catch { if (notify) Show("The priority preference was saved; Windows has not applied it to every owned process yet.", true); }
                }
            }
        }
        private void ChangePriority(string value)
        {
            try { SetPriority(value, true); }
            catch { Show("The priority preference could not be saved.", true); }
        }
        private void SetPriority(string value, bool notify)
        {
            WriteControl(Data.Bool(control, "paused", Data.Bool(status, "localPaused")), value);
            ApplyPriority(notify); RefreshState();
        }
        private async Task Toggle()
        {
            await SetPaused(!IsPaused());
        }
        private async Task<bool> SetPaused(bool paused)
        {
            if (toggling) return false;
            toggling = true; pause.Enabled = false;
            try
            {
                WriteControl(paused, DesiredPriority());
                if (!paused && !selfTest) { lastLaunchAttempt = 0; EnsureRunner(); }
                RefreshState();
                try { await remote.Running(!paused); Show(paused ? "Computation paused. Checkpoints are retained." : "Computation resumed."); return true; }
                catch { Show("The local " + (paused ? "pause" : "resume") + " is saved. Site synchronization is pending; check the connection.", true); return false; }
            }
            catch { Show("The local pause/resume control could not be saved.", true); throw; }
            finally { toggling = false; RefreshState(); }
        }
        private async Task SaveResults(string path)
        {
            if (!Path.IsPathRooted(path)) throw new InvalidOperationException("Choose an absolute output path.");
            string text = await remote.Export(); Data.AtomicText(path, text);
        }
        private async Task Download()
        {
            if (downloading) return;
            using (SaveFileDialog dialog = new SaveFileDialog { Title = "Download DexFraggler table results", Filter = "DexFraggler table (*.dxtable.json)|*.dxtable.json|JSON (*.json)|*.json", FileName = "DexFraggler-table-" + DateTime.Now.ToString("yyyyMMdd-HHmm") + ".dxtable.json", AddExtension = true, DefaultExt = "dxtable.json", OverwritePrompt = true })
            {
                if (dialog.ShowDialog() != DialogResult.OK) return;
                downloading = true; download.Enabled = false;
                try { await SaveResults(dialog.FileName); Show("Table results saved."); }
                catch (InvalidOperationException e) { Show(e.Message, true); }
                catch { Show("Table download failed. Existing files have not been replaced.", true); }
                finally { downloading = false; download.Enabled = true; }
            }
        }
        public async Task<Dictionary<string, object>> ExecuteCommand(string command, string value, string output)
        {
            Dictionary<string, object> result = new Dictionary<string, object> { { "command", command } };
            if (command == "pause" || command == "resume")
            {
                bool paused = command == "pause";
                result["siteSynchronized"] = await SetPaused(paused);
                result["paused"] = paused; result["localSaved"] = true;
            }
            else if (command == "priority")
            {
                SetPriority(value, false); result["priority"] = DesiredPriority(); result["localSaved"] = true;
                using (Process worker = OwnedWorker()) result["ownedWorkerPriority"] = worker == null ? null : worker.PriorityClass.ToString();
            }
            else if (command == "download-to-path")
            {
                await SaveResults(output); result["path"] = Path.GetFullPath(output); result["bytes"] = new FileInfo(output).Length;
            }
            else throw new InvalidOperationException("Use pause, resume, priority or download-to-path.");
            result["ok"] = true; return result;
        }
        private void ExitPaused()
        {
            try { WriteControl(true, DesiredPriority()); }
            catch { Show("Pause could not be saved. The tray remains open so you can retry.", true); return; }
            // The runner reads this local control. No process is terminated, and the native
            // renderer is left to finish its current bounded operation/checkpoint.
            exiting = true; timer.Stop(); tray.Visible = false; WriteTrayStatus(false); ExitThread();
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing) { exiting = true; timer.Stop(); timer.Dispose(); tray.Visible = false; WriteTrayStatus(false); tray.Dispose(); menu.Dispose(); icon.Dispose(); }
            base.Dispose(disposing);
        }
    }

    internal static class Program
    {
        private static string Argument(string[] args, string name)
        {
            for (int i = 0; i < args.Length - 1; i++) if (args[i] == name) return args[i + 1];
            return null;
        }
        private static string MutexName(string root)
        {
            using (SHA256 hash = SHA256.Create()) return "Local\\DexFragglerTray-" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(Data.Canonical(root).ToLowerInvariant()))).Replace("-", "");
        }
        [STAThread]
        public static int Main(string[] args)
        {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            string iconPath = Argument(args, "--write-icon");
            if (iconPath != null) { using (Icon icon = Art.CreateIcon()) using (FileStream file = File.Create(iconPath)) icon.Save(file); return 0; }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            if (args.Contains("--self-test")) return SelfTest(Argument(args, "--report"));
            string root = Argument(args, "--root");
            if (root == null || !Directory.Exists(root)) { MessageBox.Show("Start DexFraggler with --root followed by its project folder.", "DexFraggler", MessageBoxButtons.OK, MessageBoxIcon.Information); return 2; }
            if (args.Contains("--status")) return Status(root, Argument(args, "--report"));
            string command = Argument(args, "--command");
            if (command != null) return Command(root, command, Argument(args, "--value"), Argument(args, "--output"), Argument(args, "--report"));
            if (args.Contains("--open"))
            {
                try { Process.Start(new ProcessStartInfo(new Remote(root).Site().AbsoluteUri) { UseShellExecute = true }); }
                catch { MessageBox.Show("The site could not be opened. Check this project's runner configuration and default browser.", "DexFraggler", MessageBoxButtons.OK, MessageBoxIcon.Information); }
            }
            bool created;
            using (Mutex mutex = new Mutex(true, MutexName(root), out created))
            {
                if (!created) return 0;
                try { using (TrayContext context = new TrayContext(root, false)) Application.Run(context); }
                finally { mutex.ReleaseMutex(); }
            }
            return 0;
        }
        private static void Report(string path, object value)
        {
            string text = Data.Serializer().Serialize(value);
            if (path != null) Data.AtomicText(Path.GetFullPath(path), text);
            try { Console.WriteLine(text); } catch { }
        }
        private static int Status(string root, string reportPath)
        {
            Dictionary<string, object> receipt = Data.Read(Path.Combine(root, ".runtime", "tray-status.json"));
            bool owned = false;
            try
            {
                using (Process process = Process.GetProcessById((int)Data.Number(receipt, "pid")))
                    owned = !process.HasExited && Data.SamePath(root, Data.Text(receipt, "root"))
                        && Data.SamePath(process.MainModule.FileName, Data.Text(receipt, "executable"))
                        && String.Equals(Path.GetFileName(process.MainModule.FileName), "DexFraggler.Tray.exe", StringComparison.OrdinalIgnoreCase)
                        && Math.Abs(Ownership.StartTime(process) - Data.Timestamp(receipt, "processStartTime")) < 1000;
            }
            catch { }
            bool fresh = Data.Now - Data.Timestamp(receipt, "updatedAt") < 10000;
            bool alive = owned && fresh && Data.Bool(receipt, "notifyIconInitialized") && Data.Bool(receipt, "notifyIconVisible");
            Report(reportPath, new { alive = alive, processVerified = owned, uiHeartbeatFresh = fresh, tray = receipt, readOnly = true, checkedAt = Data.Now });
            return alive ? 0 : 3;
        }
        private static int Command(string root, string command, string value, string output, string reportPath)
        {
            int exit = 1;
            using (TrayContext context = new TrayContext(root, true))
            using (System.Windows.Forms.Timer trigger = new System.Windows.Forms.Timer { Interval = 10 })
            {
                trigger.Tick += async delegate
                {
                    trigger.Stop();
                    try { Report(reportPath, await context.ExecuteCommand(command, value, output)); exit = 0; }
                    catch { Report(reportPath, new { ok = false, command = command, error = "Command failed. Check the configuration, command value, output path or connection." }); }
                    finally { context.ExitThread(); }
                };
                trigger.Start(); Application.Run(context);
            }
            return exit;
        }
        private static int SelfTest(string reportPath)
        {
            string testRoot = Path.Combine(Path.GetTempPath(), "DexFragglerTray-self-test-" + Guid.NewGuid().ToString("N"));
            Dictionary<string, object> report = new Dictionary<string, object>();
            report["testRoot"] = testRoot; report["interactiveWindows"] = false;
            try
            {
                Directory.CreateDirectory(testRoot);
                using (TrayContext tray = new TrayContext(testRoot, true))
                {
                    if (tray.MenuCount != 9 || tray.PriorityCount != 5) throw new Exception("Menu construction failed.");
                    tray.WriteControl(true, "BelowNormal");
                    string path = Path.Combine(testRoot, ".runtime", "runner-control.json");
                    if (!Data.Bool(Data.Read(path), "paused")) throw new Exception("Pause persistence failed.");
                    tray.WriteControl(false, "High");
                    Dictionary<string, object> control = Data.Read(path);
                    if (Data.Bool(control, "paused") || Data.Text(control, "priority") != "High" || Data.Number(control, "updatedAt") <= 0) throw new Exception("Atomic overwrite failed.");
                    using (Process wrong = Ownership.Worker(testRoot, new Dictionary<string, object> { { "pid", Process.GetCurrentProcess().Id }, { "processStartTime", Data.Now } }))
                        if (wrong != null) throw new Exception("Unrelated process accepted as owned.");
                    report["notifyIconCreatedHidden"] = true; report["menuItems"] = tray.MenuCount; report["priorityChoices"] = tray.PriorityCount;
                }
                report["controlRoundTrip"] = true; report["unrelatedProcessRejected"] = true;
                report["networkRequests"] = 0; report["liveProcessesStartedOrChanged"] = 0; report["passed"] = true;
            }
            catch (Exception e) { report["passed"] = false; report["error"] = e.GetType().Name + ": " + e.Message; }
            report["finishedAt"] = Data.Now;
            if (reportPath == null) reportPath = Path.Combine(testRoot, "self-test.json");
            Data.AtomicJson(Path.GetFullPath(reportPath), report);
            return Data.Bool(report, "passed") ? 0 : 1;
        }
    }
}
