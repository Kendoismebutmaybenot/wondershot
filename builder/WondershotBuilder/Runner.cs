using System.Diagnostics;
using System.IO;
using System.Text;

namespace WondershotBuilder;

/// Where nx2/make_wonder.py and a Python to run it are: a "tools" folder beside the app when packaged, or the source tree the
/// app sits in (builder\WondershotBuilder\bin\...), with WONDERSHOT_PYTHON (or the PC's Python) for it.
sealed record Tools(string Root, string Python, string[] PythonArgs)
{
    public string Script => Path.Combine(Root, "nx2", "make_wonder.py");

    public static Tools? Find()
    {
        var at = AppContext.BaseDirectory;
        var bundled = Path.Combine(at, "tools");
        if (File.Exists(Path.Combine(bundled, "nx2", "make_wonder.py")))
        {
            var own = Path.Combine(bundled, "python", "python.exe");
            // (a package with a Python of its own runs no other)
            return new Tools(bundled, File.Exists(own) || Directory.Exists(Path.Combine(bundled, "python")) ? own : "python", []);
        }
        for (var d = new DirectoryInfo(at); d != null; d = d.Parent)
            if (File.Exists(Path.Combine(d.FullName, "nx2", "make_wonder.py")))
            {
                var env = Environment.GetEnvironmentVariable("WONDERSHOT_PYTHON");
                if (!string.IsNullOrEmpty(env) && File.Exists(env)) return new Tools(d.FullName, env, []);
                var (exe, args) = PythonOnPath();
                return new Tools(d.FullName, exe, args);
            }
        return null;
    }

    /// Windows' Store shortcut is not an interpreter: the py launcher is tried when "python" is that
    static (string Exe, string[] Args) PythonOnPath()
    {
        var python = AllOnPath("python.exe").FirstOrDefault(p => !p.Contains(@"\Microsoft\WindowsApps\", StringComparison.OrdinalIgnoreCase));
        if (python != null) return (python, []);
        var py = AllOnPath("py.exe").FirstOrDefault();
        return py != null ? (py, ["-3"]) : ("python", []);
    }

    static IEnumerable<string> AllOnPath(string name)
    {
        foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
            if (!string.IsNullOrWhiteSpace(dir))
            {
                var path = Path.Combine(dir.Trim('"'), name);
                if (File.Exists(path)) yield return path;
            }
    }
}

/// nx2/make_wonder.py as a child process: its lines as they come, and how it ended. Its lines the app reads:
///   @@stage <id> <text>   @@progress <0..1>   @@eta <seconds>   @@check ok|bad <text>   @@done <folder>   @@error <text>
sealed class Runner
{
    readonly Tools tools;
    readonly List<string> args;
    Process? process;
    string? error;
    volatile bool cancelled;

    public event Action<string>? Line;
    public event Action<string?>? Finished;

    public Runner(Tools tools, IEnumerable<string> args)
    {
        this.tools = tools;
        this.args = args.ToList();
    }

    public void Start()
    {
        var psi = new ProcessStartInfo(tools.Python)
        {
            WorkingDirectory = tools.Root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        foreach (var a in tools.PythonArgs) psi.ArgumentList.Add(a);
        foreach (var a in new[] { "-I", "-u", "-X", "utf8", tools.Script }) psi.ArgumentList.Add(a);
        foreach (var a in args) psi.ArgumentList.Add(a);
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        try
        {
            process = Process.Start(psi);
        }
        catch (Exception e) when (e is System.ComponentModel.Win32Exception or IOException)
        {
            Finished?.Invoke("Python could not be started: " + e.Message);
            return;
        }
        if (process == null) { Finished?.Invoke("Python could not be started."); return; }
        var p = process;
        void Take(string? line)
        {
            if (line == null) return;
            if (line.StartsWith("@@error ")) error = line[8..];
            Line?.Invoke(line);
        }
        p.OutputDataReceived += (_, e) => Take(e.Data);
        p.ErrorDataReceived += (_, e) => Take(e.Data);
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        p.EnableRaisingEvents = true;
        p.Exited += (_, _) =>
        {
            p.WaitForExit();   // (the last lines read before this ends)
            Finished?.Invoke(cancelled ? "cancelled" : p.ExitCode == 0 ? null : error ?? $"The build stopped (exit code {p.ExitCode}).");
        };
    }

    /// Stops the build and everything it started (the compilers)
    public void Cancel()
    {
        cancelled = true;
        try { process?.Kill(true); } catch (InvalidOperationException) { }
    }
}
