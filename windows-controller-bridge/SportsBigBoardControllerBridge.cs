using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace SportsBigBoard
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            using (BridgeService service = new BridgeService())
            {
                service.Start();
                Application.Run(new BridgeApplicationContext(service));
            }
        }
    }

    internal sealed class BridgeApplicationContext : ApplicationContext
    {
        private readonly BridgeService service;
        private readonly NotifyIcon tray;
        private readonly ToolStripMenuItem statusItem;
        private readonly System.Windows.Forms.Timer timer;

        public BridgeApplicationContext(BridgeService service)
        {
            this.service = service;
            statusItem = new ToolStripMenuItem("Starting...");
            statusItem.Enabled = false;
            ToolStripMenuItem open = new ToolStripMenuItem("Open Sports Big Board");
            open.Click += delegate { OpenUrl("https://jonathanjoelneptune.github.io/sports-big-board/"); };
            ToolStripMenuItem copy = new ToolStripMenuItem("Copy bridge status");
            copy.Click += delegate { try { Clipboard.SetText(service.StatusDetail); } catch { } };
            ToolStripMenuItem quit = new ToolStripMenuItem("Quit");
            quit.Click += delegate { ExitThread(); };
            ContextMenuStrip menu = new ContextMenuStrip();
            menu.Items.Add(new ToolStripMenuItem("Sports Big Board Controller Bridge") { Enabled = false });
            menu.Items.Add(statusItem);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(open);
            menu.Items.Add(copy);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(quit);

            tray = new NotifyIcon();
            tray.Icon = SystemIcons.Application;
            tray.Text = "Sports Big Board Controller Bridge";
            tray.Visible = true;
            tray.ContextMenuStrip = menu;
            tray.DoubleClick += delegate { OpenUrl("https://jonathanjoelneptune.github.io/sports-big-board/"); };

            timer = new System.Windows.Forms.Timer();
            timer.Interval = 750;
            timer.Tick += delegate { RefreshStatus(); };
            timer.Start();
            RefreshStatus();
        }

        private static void OpenUrl(string url)
        {
            try { Process.Start(url); }
            catch
            {
                try { Process.Start(new ProcessStartInfo("cmd", "/c start \"\" \"" + url + "\"") { CreateNoWindow = true }); }
                catch { }
            }
        }

        private void RefreshStatus()
        {
            string text = service.ShortStatus;
            statusItem.Text = text;
            string tip = "SBB Controller Bridge • " + text;
            if (tip.Length > 63) tip = tip.Substring(0, 63);
            try { tray.Text = tip; } catch { }
        }

        protected override void ExitThreadCore()
        {
            timer.Stop();
            service.Stop();
            tray.Visible = false;
            tray.Dispose();
            timer.Dispose();
            base.ExitThreadCore();
        }
    }

    internal sealed class BridgeService : IDisposable
    {
        public const int Port = 5410;
        public const int ProtocolVersion = 1;
        public const string BridgeVersion = "5.4.7";
        private TcpListener listener;
        private Thread listenerThread;
        private volatile bool running;
        private int clientCount;
        private int commandCount;
        private string lastController = "No controller";
        private string lastSource = "";
        private string lastCommand = "none";
        private readonly object statusLock = new object();

        public string ShortStatus
        {
            get
            {
                lock (statusLock)
                {
                    string clients = clientCount > 0 ? " • Big Board connected" : " • waiting for Big Board";
                    return lastController + clients;
                }
            }
        }

        public string StatusDetail
        {
            get
            {
                lock (statusLock)
                {
                    return "Sports Big Board Controller Bridge v" + BridgeVersion + Environment.NewLine +
                           "Loopback: ws://127.0.0.1:" + Port + "/sbb-controller" + Environment.NewLine +
                           "Controller: " + lastController + Environment.NewLine +
                           "Source: " + (lastSource.Length == 0 ? "none" : lastSource) + Environment.NewLine +
                           "Browser clients: " + clientCount.ToString(CultureInfo.InvariantCulture) + Environment.NewLine +
                           "Fullscreen commands: " + commandCount.ToString(CultureInfo.InvariantCulture) + Environment.NewLine +
                           "Last command: " + lastCommand;
                }
            }
        }

        public void Start()
        {
            if (running) return;
            running = true;
            listenerThread = new Thread(ListenLoop);
            listenerThread.IsBackground = true;
            listenerThread.Name = "SBB Controller Bridge Listener";
            listenerThread.Start();
        }

        public void Stop()
        {
            running = false;
            try { if (listener != null) listener.Stop(); } catch { }
            try { if (listenerThread != null && listenerThread.IsAlive) listenerThread.Join(700); } catch { }
        }

        public void Dispose() { Stop(); }

        private void ListenLoop()
        {
            try
            {
                listener = new TcpListener(IPAddress.Loopback, Port);
                listener.Start();
                while (running)
                {
                    TcpClient client;
                    try { client = listener.AcceptTcpClient(); }
                    catch { if (!running) break; else continue; }
                    Thread t = new Thread(new ThreadStart(delegate { HandleClient(client); }));
                    t.IsBackground = true;
                    t.Name = "SBB Controller Browser Client";
                    t.Start();
                }
            }
            catch (Exception ex)
            {
                lock (statusLock) { lastController = "Bridge error: " + ex.Message; lastSource = "listener"; }
            }
        }

        private void HandleClient(TcpClient client)
        {
            bool upgraded = false;
            try
            {
                client.NoDelay = true;
                NetworkStream stream = client.GetStream();
                string request = ReadHttpHeaders(stream);
                if (request == null) return;
                Dictionary<string, string> headers = ParseHeaders(request);
                string origin;
                headers.TryGetValue("origin", out origin);
                if (!OriginAllowed(origin))
                {
                    WriteHttp(stream, "403 Forbidden", "text/plain", "Origin not allowed", null);
                    return;
                }
                if (request.StartsWith("OPTIONS ", StringComparison.OrdinalIgnoreCase))
                {
                    WriteHttp(stream, "204 No Content", "text/plain", "", origin);
                    return;
                }
                string upgrade;
                headers.TryGetValue("upgrade", out upgrade);
                string key;
                headers.TryGetValue("sec-websocket-key", out key);
                if (!string.Equals(upgrade, "websocket", StringComparison.OrdinalIgnoreCase) || string.IsNullOrEmpty(key))
                {
                    WriteHttp(stream, "200 OK", "application/json", "{\"service\":\"Sports Big Board Controller Bridge\",\"version\":\"" + BridgeVersion + "\",\"protocol\":" + ProtocolVersion.ToString(CultureInfo.InvariantCulture) + "}", origin);
                    return;
                }
                string accept = WebSocketAccept(key);
                string response = "HTTP/1.1 101 Switching Protocols\r\n" +
                                  "Upgrade: websocket\r\n" +
                                  "Connection: Upgrade\r\n" +
                                  "Sec-WebSocket-Accept: " + accept + "\r\n\r\n";
                byte[] responseBytes = Encoding.ASCII.GetBytes(response);
                stream.Write(responseBytes, 0, responseBytes.Length);
                upgraded = true;
                Interlocked.Increment(ref clientCount);
                SendText(stream, "{\"type\":\"hello\",\"protocol\":1,\"bridgeVersion\":\"" + BridgeVersion + "\",\"name\":\"Sports Big Board Controller Bridge\"}");

                long seq = 0;
                string previous = "";
                DateTime lastSend = DateTime.MinValue;
                while (running && client.Connected)
                {
                    ControllerSnapshot state = ControllerReader.Read();
                    lock (statusLock)
                    {
                        lastController = state.Connected ? state.Id : "No controller";
                        lastSource = state.Source;
                    }
                    string stateKey = state.ToJson(0);
                    bool heartbeat = (DateTime.UtcNow - lastSend).TotalMilliseconds >= 850;
                    if (stateKey != previous || heartbeat)
                    {
                        SendText(stream, state.ToJson(++seq));
                        previous = stateKey;
                        lastSend = DateTime.UtcNow;
                    }
                    // Browser-to-bridge traffic is intentionally tiny and whitelisted.
                    // It exists only so controller input can invoke fullscreen actions
                    // that Chromium refuses from Gamepad/WebSocket callbacks because
                    // those callbacks are not trusted transient user activations.
                    if (stream.DataAvailable)
                    {
                        string commandFrame = TryReadClientTextFrame(stream);
                        if (!string.IsNullOrEmpty(commandFrame)) HandleCommand(commandFrame, stream);
                    }
                    Thread.Sleep(16);
                }
            }
            catch { }
            finally
            {
                if (upgraded) Interlocked.Decrement(ref clientCount);
                try { client.Close(); } catch { }
            }
        }

        private static string ReadHttpHeaders(NetworkStream stream)
        {
            MemoryStream ms = new MemoryStream();
            int matched = 0;
            while (ms.Length < 16384)
            {
                int b = stream.ReadByte();
                if (b < 0) return null;
                ms.WriteByte((byte)b);
                if ((matched == 0 && b == '\r') || (matched == 1 && b == '\n') || (matched == 2 && b == '\r') || (matched == 3 && b == '\n'))
                {
                    matched++;
                    if (matched == 4) break;
                }
                else matched = b == '\r' ? 1 : 0;
            }
            return Encoding.ASCII.GetString(ms.ToArray());
        }

        private static Dictionary<string, string> ParseHeaders(string request)
        {
            Dictionary<string, string> result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            string[] lines = request.Split(new string[] { "\r\n" }, StringSplitOptions.None);
            for (int i = 1; i < lines.Length; i++)
            {
                int colon = lines[i].IndexOf(':');
                if (colon <= 0) continue;
                result[lines[i].Substring(0, colon).Trim()] = lines[i].Substring(colon + 1).Trim();
            }
            return result;
        }

        private static bool OriginAllowed(string origin)
        {
            if (string.IsNullOrEmpty(origin)) return false;
            Uri uri;
            if (!Uri.TryCreate(origin, UriKind.Absolute, out uri)) return false;
            string host = uri.Host.ToLowerInvariant();
            if (host == "jonathanjoelneptune.github.io" && uri.Scheme == "https") return true;
            if ((host == "127.0.0.1" || host == "localhost" || host == "::1") && (uri.Scheme == "http" || uri.Scheme == "https")) return true;
            return false;
        }

        private void HandleCommand(string json, NetworkStream stream)
        {
            if (string.IsNullOrEmpty(json) || json.IndexOf("\"type\":\"command\"", StringComparison.OrdinalIgnoreCase) < 0) return;
            string command = "";
            if (json.IndexOf("\"command\":\"app-fullscreen\"", StringComparison.OrdinalIgnoreCase) >= 0) command = "app-fullscreen";
            else if (json.IndexOf("\"command\":\"video-fullscreen\"", StringComparison.OrdinalIgnoreCase) >= 0) command = "video-fullscreen";
            if (command.Length == 0) return;
            bool ok = command == "app-fullscreen" ? KeyboardCommand.Tap(0x7A) : KeyboardCommand.Tap(0x46); // F11 / F
            lock (statusLock) { commandCount++; lastCommand = command + (ok ? " • sent" : " • FAILED"); }
            try { SendText(stream, "{\"type\":\"command-result\",\"protocol\":1,\"bridgeVersion\":\"" + BridgeVersion + "\",\"command\":\"" + command + "\",\"ok\":" + (ok ? "true" : "false") + "}"); } catch { }
        }

        private static string TryReadClientTextFrame(NetworkStream stream)
        {
            try
            {
                int first = stream.ReadByte(); if (first < 0) return null;
                int second = stream.ReadByte(); if (second < 0) return null;
                int opcode = first & 0x0F;
                bool masked = (second & 0x80) != 0;
                ulong length = (ulong)(second & 0x7F);
                if (length == 126)
                {
                    int a = stream.ReadByte(), b = stream.ReadByte(); if (a < 0 || b < 0) return null;
                    length = (ulong)((a << 8) | b);
                }
                else if (length == 127) return null; // Commands are always tiny.
                if (!masked || length > 2048) return null;
                byte[] mask = ReadExact(stream, 4); if (mask == null) return null;
                byte[] payload = ReadExact(stream, (int)length); if (payload == null) return null;
                for (int i = 0; i < payload.Length; i++) payload[i] = (byte)(payload[i] ^ mask[i % 4]);
                if (opcode == 0x8) return null;
                if (opcode != 0x1) return null;
                return Encoding.UTF8.GetString(payload);
            }
            catch { return null; }
        }

        private static byte[] ReadExact(NetworkStream stream, int count)
        {
            byte[] data = new byte[count]; int offset = 0;
            while (offset < count)
            {
                int n = stream.Read(data, offset, count - offset); if (n <= 0) return null; offset += n;
            }
            return data;
        }

        private static void WriteHttp(NetworkStream stream, string status, string contentType, string body, string origin)
        {
            byte[] payload = Encoding.UTF8.GetBytes(body);
            StringBuilder header = new StringBuilder();
            header.Append("HTTP/1.1 ").Append(status).Append("\r\n");
            header.Append("Content-Type: ").Append(contentType).Append("\r\n");
            header.Append("Content-Length: ").Append(payload.Length.ToString(CultureInfo.InvariantCulture)).Append("\r\n");
            if (!string.IsNullOrEmpty(origin))
            {
                header.Append("Access-Control-Allow-Origin: ").Append(origin).Append("\r\n");
                header.Append("Vary: Origin\r\n");
                header.Append("Access-Control-Allow-Methods: GET, OPTIONS\r\n");
                header.Append("Access-Control-Allow-Headers: Content-Type\r\n");
                header.Append("Access-Control-Allow-Private-Network: true\r\n");
            }
            header.Append("Connection: close\r\n\r\n");
            byte[] h = Encoding.ASCII.GetBytes(header.ToString());
            stream.Write(h, 0, h.Length);
            stream.Write(payload, 0, payload.Length);
        }

        private static string WebSocketAccept(string key)
        {
            byte[] input = Encoding.ASCII.GetBytes(key.Trim() + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11");
            using (SHA1 sha = SHA1.Create()) return Convert.ToBase64String(sha.ComputeHash(input));
        }

        private static void SendText(NetworkStream stream, string text)
        {
            byte[] payload = Encoding.UTF8.GetBytes(text);
            using (MemoryStream frame = new MemoryStream())
            {
                frame.WriteByte(0x81);
                if (payload.Length <= 125)
                {
                    frame.WriteByte((byte)payload.Length);
                }
                else if (payload.Length <= ushort.MaxValue)
                {
                    frame.WriteByte(126);
                    frame.WriteByte((byte)((payload.Length >> 8) & 0xff));
                    frame.WriteByte((byte)(payload.Length & 0xff));
                }
                else
                {
                    frame.WriteByte(127);
                    ulong len = (ulong)payload.LongLength;
                    for (int i = 7; i >= 0; i--) frame.WriteByte((byte)((len >> (i * 8)) & 0xff));
                }
                frame.Write(payload, 0, payload.Length);
                byte[] bytes = frame.ToArray();
                stream.Write(bytes, 0, bytes.Length);
                stream.Flush();
            }
        }
    }

    internal static class KeyboardCommand
    {
        private const uint INPUT_KEYBOARD = 1;
        private const uint KEYEVENTF_KEYUP = 0x0002;
        [StructLayout(LayoutKind.Sequential)]
        private struct INPUT
        {
            public uint type;
            public INPUTUNION U;
        }
        [StructLayout(LayoutKind.Explicit)]
        private struct INPUTUNION
        {
            [FieldOffset(0)] public KEYBDINPUT ki;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct KEYBDINPUT
        {
            public ushort wVk;
            public ushort wScan;
            public uint dwFlags;
            public uint time;
            public UIntPtr dwExtraInfo;
        }
        [DllImport("user32.dll", SetLastError = true)] private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);
        [DllImport("user32.dll")] private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
        public static bool Tap(byte key)
        {
            try
            {
                INPUT down = new INPUT(); down.type = INPUT_KEYBOARD; down.U.ki.wVk = key;
                INPUT up = new INPUT(); up.type = INPUT_KEYBOARD; up.U.ki.wVk = key; up.U.ki.dwFlags = KEYEVENTF_KEYUP;
                INPUT[] inputs = new INPUT[] { down, up };
                uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
                if (sent == (uint)inputs.Length) return true;
            }
            catch { }
            // Compatibility fallback for unusual Windows input stacks.
            try
            {
                keybd_event(key, 0, 0, UIntPtr.Zero);
                Thread.Sleep(24);
                keybd_event(key, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
                return true;
            }
            catch { return false; }
        }
    }

    internal sealed class ControllerSnapshot
    {
        public bool Connected;
        public string Id = "Windows Controller";
        public string Source = "";
        public double[] Buttons = new double[18];
        public double[] Axes = new double[4];

        public string ToJson(long sequence)
        {
            StringBuilder sb = new StringBuilder(512);
            sb.Append("{\"type\":\"state\",\"protocol\":1,\"bridgeVersion\":\"5.4.7\",\"sequence\":");
            sb.Append(sequence.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"connected\":").Append(Connected ? "true" : "false");
            sb.Append(",\"id\":\"").Append(JsonEscape(Id)).Append("\"");
            sb.Append(",\"source\":\"").Append(JsonEscape(Source)).Append("\"");
            sb.Append(",\"buttons\":[");
            for (int i = 0; i < Buttons.Length; i++) { if (i > 0) sb.Append(','); sb.Append(Buttons[i].ToString("0.####", CultureInfo.InvariantCulture)); }
            sb.Append("],\"axes\":[");
            for (int i = 0; i < Axes.Length; i++) { if (i > 0) sb.Append(','); sb.Append(Axes[i].ToString("0.####", CultureInfo.InvariantCulture)); }
            sb.Append("]}");
            return sb.ToString();
        }

        private static string JsonEscape(string value)
        {
            if (value == null) return "";
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", " ").Replace("\n", " ");
        }
    }

    internal static class ControllerReader
    {
        private const ushort DPAD_UP = 0x0001, DPAD_DOWN = 0x0002, DPAD_LEFT = 0x0004, DPAD_RIGHT = 0x0008;
        private const ushort START = 0x0010, BACK = 0x0020, LEFT_THUMB = 0x0040, RIGHT_THUMB = 0x0080;
        private const ushort LEFT_SHOULDER = 0x0100, RIGHT_SHOULDER = 0x0200;
        private const ushort A = 0x1000, B = 0x2000, X = 0x4000, Y = 0x8000;
        private static readonly XInputGetStateDelegate xinput = ResolveXInput();

        [StructLayout(LayoutKind.Sequential)]
        private struct XINPUT_GAMEPAD
        {
            public ushort wButtons;
            public byte bLeftTrigger;
            public byte bRightTrigger;
            public short sThumbLX;
            public short sThumbLY;
            public short sThumbRX;
            public short sThumbRY;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct XINPUT_STATE { public uint dwPacketNumber; public XINPUT_GAMEPAD Gamepad; }
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        private delegate uint XInputGetStateDelegate(uint dwUserIndex, out XINPUT_STATE pState);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr LoadLibrary(string lpFileName);
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)] private static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);

        [StructLayout(LayoutKind.Sequential)]
        private struct JOYINFOEX
        {
            public uint dwSize, dwFlags, dwXpos, dwYpos, dwZpos, dwRpos, dwUpos, dwVpos, dwButtons, dwButtonNumber, dwPOV, dwReserved1, dwReserved2;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
        private struct JOYCAPS
        {
            public ushort wMid, wPid;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string szPname;
            public uint wXmin, wXmax, wYmin, wYmax, wZmin, wZmax, wNumButtons, wPeriodMin, wPeriodMax, wRmin, wRmax, wUmin, wUmax, wVmin, wVmax;
            public uint wCaps, wMaxAxes, wNumAxes, wMaxButtons;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string szRegKey;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string szOEMVxD;
        }
        [DllImport("winmm.dll")] private static extern uint joyGetNumDevs();
        [DllImport("winmm.dll")] private static extern uint joyGetPosEx(uint uJoyID, ref JOYINFOEX pji);
        [DllImport("winmm.dll", CharSet = CharSet.Auto)] private static extern uint joyGetDevCaps(uint uJoyID, ref JOYCAPS pjc, uint cbjc);
        private const uint JOYERR_NOERROR = 0;
        private const uint JOY_RETURNALL = 0x000000FF;
        private const uint JOY_POVCENTERED = 0x0000FFFF;

        public static ControllerSnapshot Read()
        {
            ControllerSnapshot s;
            if (TryXInput(out s)) return s;
            if (TryWinMM(out s)) return s;
            return new ControllerSnapshot { Connected = false, Id = "No controller", Source = "Windows" };
        }

        private static XInputGetStateDelegate ResolveXInput()
        {
            string[] dlls = { "xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll" };
            for (int i = 0; i < dlls.Length; i++)
            {
                try
                {
                    IntPtr h = LoadLibrary(dlls[i]);
                    if (h == IntPtr.Zero) continue;
                    IntPtr p = GetProcAddress(h, "XInputGetState");
                    if (p != IntPtr.Zero) return (XInputGetStateDelegate)Marshal.GetDelegateForFunctionPointer(p, typeof(XInputGetStateDelegate));
                }
                catch { }
            }
            return null;
        }

        private static bool TryXInput(out ControllerSnapshot result)
        {
            result = null;
            if (xinput == null) return false;
            for (uint slot = 0; slot < 4; slot++)
            {
                XINPUT_STATE state;
                uint err;
                try { err = xinput(slot, out state); } catch { return false; }
                if (err != 0) continue;
                XINPUT_GAMEPAD g = state.Gamepad;
                ControllerSnapshot s = new ControllerSnapshot();
                s.Connected = true;
                s.Id = "Xbox-compatible Controller " + (slot + 1).ToString(CultureInfo.InvariantCulture);
                s.Source = "XInput";
                SetDigital(s, 0, (g.wButtons & A) != 0); SetDigital(s, 1, (g.wButtons & B) != 0); SetDigital(s, 2, (g.wButtons & X) != 0); SetDigital(s, 3, (g.wButtons & Y) != 0);
                SetDigital(s, 4, (g.wButtons & LEFT_SHOULDER) != 0); SetDigital(s, 5, (g.wButtons & RIGHT_SHOULDER) != 0);
                s.Buttons[6] = g.bLeftTrigger / 255.0; s.Buttons[7] = g.bRightTrigger / 255.0;
                SetDigital(s, 8, (g.wButtons & BACK) != 0); SetDigital(s, 9, (g.wButtons & START) != 0);
                SetDigital(s, 10, (g.wButtons & LEFT_THUMB) != 0); SetDigital(s, 11, (g.wButtons & RIGHT_THUMB) != 0);
                SetDigital(s, 12, (g.wButtons & DPAD_UP) != 0); SetDigital(s, 13, (g.wButtons & DPAD_DOWN) != 0); SetDigital(s, 14, (g.wButtons & DPAD_LEFT) != 0); SetDigital(s, 15, (g.wButtons & DPAD_RIGHT) != 0);
                s.Axes[0] = NormalizeStick(g.sThumbLX); s.Axes[1] = -NormalizeStick(g.sThumbLY); s.Axes[2] = NormalizeStick(g.sThumbRX); s.Axes[3] = -NormalizeStick(g.sThumbRY);
                result = s; return true;
            }
            return false;
        }

        private static double NormalizeStick(short value)
        {
            if (value >= 0) return Math.Min(1.0, value / 32767.0);
            return Math.Max(-1.0, value / 32768.0);
        }
        private static void SetDigital(ControllerSnapshot s, int index, bool value) { s.Buttons[index] = value ? 1.0 : 0.0; }

        private static bool TryWinMM(out ControllerSnapshot result)
        {
            result = null;
            uint count;
            try { count = joyGetNumDevs(); } catch { return false; }
            for (uint id = 0; id < count; id++)
            {
                JOYINFOEX info = new JOYINFOEX(); info.dwSize = (uint)Marshal.SizeOf(typeof(JOYINFOEX)); info.dwFlags = JOY_RETURNALL;
                if (joyGetPosEx(id, ref info) != JOYERR_NOERROR) continue;
                JOYCAPS caps = new JOYCAPS(); joyGetDevCaps(id, ref caps, (uint)Marshal.SizeOf(typeof(JOYCAPS)));
                ControllerSnapshot s = new ControllerSnapshot(); s.Connected = true; s.Id = string.IsNullOrEmpty(caps.szPname) ? "Windows Game Controller " + (id + 1).ToString(CultureInfo.InvariantCulture) : caps.szPname; s.Source = "WinMM";
                for (int b = 0; b < 10; b++) SetDigital(s, b, (info.dwButtons & (1u << b)) != 0);
                if (info.dwPOV != JOY_POVCENTERED)
                {
                    int pov = (int)info.dwPOV;
                    SetDigital(s, 12, pov >= 31500 || pov <= 4500);
                    SetDigital(s, 15, pov >= 4500 && pov <= 13500);
                    SetDigital(s, 13, pov >= 13500 && pov <= 22500);
                    SetDigital(s, 14, pov >= 22500 && pov <= 31500);
                }
                s.Axes[0] = NormalizeRange(info.dwXpos, caps.wXmin, caps.wXmax);
                s.Axes[1] = NormalizeRange(info.dwYpos, caps.wYmin, caps.wYmax);
                s.Axes[2] = NormalizeRange(info.dwRpos, caps.wRmin, caps.wRmax);
                s.Axes[3] = NormalizeRange(info.dwUpos, caps.wUmin, caps.wUmax);
                double z = NormalizeRange(info.dwZpos, caps.wZmin, caps.wZmax);
                s.Buttons[6] = Math.Max(0, -z); s.Buttons[7] = Math.Max(0, z);
                result = s; return true;
            }
            return false;
        }
        private static double NormalizeRange(uint value, uint min, uint max)
        {
            if (max <= min) return 0;
            return Math.Max(-1.0, Math.Min(1.0, ((value - (double)min) / (max - (double)min)) * 2.0 - 1.0));
        }
    }
}
