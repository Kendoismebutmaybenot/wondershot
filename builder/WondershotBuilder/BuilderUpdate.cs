using System.Diagnostics;
using System.IO;

namespace WondershotBuilder;

static class BuilderUpdate
{
    public static void Start(string downloadedExe, string installFolder)
    {
        var source = Path.GetDirectoryName(Path.GetFullPath(downloadedExe))!;
        var python = Path.Combine(source, "tools", "python", "python.exe");
        var script = Path.Combine(source, "tools", "nx2", "builder_update.py");
        if (!File.Exists(python) || !File.Exists(script))
            throw new IOException("The downloaded Builder does not contain its updater.");
        var info = new ProcessStartInfo(python)
        {
            WorkingDirectory = source, UseShellExecute = false, CreateNoWindow = true,
        };
        foreach (var arg in new[] { "-I", "-u", "-X", "utf8", script, "--target", installFolder,
                                   "--wait-pid", Environment.ProcessId.ToString() })
            info.ArgumentList.Add(arg);
        using var started = Process.Start(info);
        if (started == null) throw new IOException("The Builder updater could not be started.");
    }

    public static void Cleanup(string[] args)
    {
        if (args.Length != 3 || args[0] != "--cleanup-builder-update" || !int.TryParse(args[2], out var pid) || pid <= 0)
            return;
        try
        {
            var source = Path.GetFullPath(args[1]);
            var install = Path.TrimEndingDirectorySeparator(Path.GetFullPath(AppContext.BaseDirectory));
            var root = Path.GetDirectoryName(install)!;
            if (Path.GetFileName(root) != "WondershotBuilder-updates") root = Path.Combine(root, "WondershotBuilder-updates");
            // Delete only a sibling update download that records this exact installation.
            if (!string.Equals(Path.GetDirectoryName(source), root, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(source, install, StringComparison.OrdinalIgnoreCase) ||
                (File.GetAttributes(source) & FileAttributes.ReparsePoint) != 0 ||
                !string.Equals(File.ReadAllText(Path.Combine(source, "builder_update_target.txt")), install,
                               StringComparison.OrdinalIgnoreCase)) return;
            _ = Task.Run(() =>
            {
                try
                {
                    try { using var updater = Process.GetProcessById(pid); if (!updater.WaitForExit(120_000)) return; }
                    catch (ArgumentException) { } // It has already exited.
                    Directory.Delete(source, recursive: true);
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.ComponentModel.Win32Exception) { }
            });
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException) { }
    }
}
