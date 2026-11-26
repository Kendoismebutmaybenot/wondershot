using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using Microsoft.Win32;

namespace WondershotBuilder;

/// A step of the rail on the left: 0 to do, 1 now, 2 done
sealed class Step : INotifyPropertyChanged
{
    int state;
    string sub;
    readonly int number;
    public Step(int number, string title, string sub) { this.number = number; Title = title; this.sub = sub; }
    public string Title { get; }
    public string Sub { get => sub; set { sub = value; Raise(nameof(Sub)); } }
    public int State { get => state; set { state = value; Raise(nameof(State)); Raise(nameof(Mark)); } }
    public string Mark => state == 2 ? "✓" : number.ToString();
    public event PropertyChangedEventHandler? PropertyChanged;
    void Raise(string name) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public partial class MainWindow : Window
{
    sealed record Settings(string? Game, string? Out, bool Copy = false, bool PortableWorkspace = true);

    const string AppDataWorkspace = @"%LOCALAPPDATA%\WondershotBuilder\work";
    const string WorkspaceDirectory = "build-workspace";
    static readonly string SettingsPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WondershotBuilder", "settings.json");

    readonly Tools? tools = Tools.Find();
    readonly ObservableCollection<Step> steps = new()
    {
        new Step(1, "Your game", "Choose your copy"),
        new Step(2, "Build tools", "Compiler and libraries"),
        new Step(3, "Build", "Recompile the game"),
        new Step(4, "Play", "All set"),
    };
    readonly StringBuilder log = new();
    StreamWriter? logFile;   // (every build's lines, as they come: a logs folder beside the Builder, one build-<time>.log each)
    string? logPath;
    /// The logs folder beside WondershotBuilder.exe, where a player looks first. A Builder in a folder it can't write to (Program
    /// Files) keeps them in %LOCALAPPDATA%\WondershotBuilder\logs instead.
    static string? logsDir;
    static string LogsDir
    {
        get
        {
            if (logsDir != null) return logsDir;
            var beside = Path.Combine(AppContext.BaseDirectory, "logs");
            try
            {
                Directory.CreateDirectory(beside);
                var probe = Path.Combine(beside, ".write-test");
                File.WriteAllText(probe, "");
                File.Delete(probe);
                return logsDir = beside;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                return logsDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WondershotBuilder", "logs");
            }
        }
    }
    Runner? runner, checker;
    string? game;
    string outDir;
    bool gameOk, building;
    string? builtFolder;
    string? buildWarning;   // (a step that did not finish but left a working game: "@@warn <text>", shown on the Done page)
    string? updateTag, updateUrl;   // (a newer release of the port than this install: its tag and its sources on GitHub)
    string? builderUpdateTag;
    bool updatingBuilder;

    public MainWindow()
    {
        InitializeComponent();
        StepList.ItemsSource = steps;
        VersionText.Text = "Wondershot Builder " + AppVersion();
        outDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Games", "Wondershot");
        try
        {
            if (File.Exists(SettingsPath) && JsonSerializer.Deserialize<Settings>(File.ReadAllText(SettingsPath)) is { } s)
            {
                if (!string.IsNullOrWhiteSpace(s.Out)) outDir = s.Out;
                if (s.Copy) FilesCopy.IsChecked = true;
                PortableWorkspace.IsChecked = s.PortableWorkspace;
                if (!string.IsNullOrWhiteSpace(s.Game) && (Directory.Exists(s.Game) || File.Exists(s.Game))) game = s.Game;
            }
        }
        catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException) { }
        OutText.Text = outDir;
        RefreshWorkspacePath();
        DragOver += (_, e) => { var ok = e.Data.GetDataPresent(DataFormats.FileDrop); e.Effects = ok ? DragDropEffects.Copy : DragDropEffects.None; DropGlow.Visibility = ok ? Visibility.Visible : Visibility.Collapsed; e.Handled = true; };
        DragLeave += (_, _) => DropGlow.Visibility = Visibility.Collapsed;
        Drop += OnDrop;
        if (tools == null) SetStatus(2, "The build tools were not found next to this program.");
        else if (game != null) UseGame(game);
        ShowStepsFor("setup");
        RefreshInstalled();
        CheckForUpdate();
    }

    static string AppVersion()
    {
        try
        {
            var version = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "builder_version.txt")).Trim();
            if (version.Length > 0) return version;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
        return typeof(MainWindow).Assembly.GetName().Version?.ToString(3) ?? "";
    }

    // ---- the window ----
    void Banner_Drag(object sender, MouseButtonEventArgs e) { if (e.ButtonState == MouseButtonState.Pressed) DragMove(); }
    void Minimize_Click(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;
    void Close_Click(object sender, RoutedEventArgs e)
    {
        if (updatingBuilder) return;
        if (building && MessageBox.Show(this, "The build is still running. Stop it and close?", "Wondershot Builder", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
        runner?.Cancel();
        Close();
    }

    // ---- the game ----
    void OnDrop(object sender, DragEventArgs e)
    {
        DropGlow.Visibility = Visibility.Collapsed;
        if (building || updatingBuilder || e.Data.GetData(DataFormats.FileDrop) is not string[] files || files.Length == 0) return;
        UseGame(files[0]);
    }

    void ChooseFolder_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog { Title = "Choose the folder with your game's exefs and romfs" };
        if (dialog.ShowDialog(this) == true) UseGame(dialog.FolderName);
    }

    void ChooseNup_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "Choose your game's .nup file", Filter = "Nintendo Switch 2 update package (*.nup)|*.nup|All files|*.*" };
        if (dialog.ShowDialog(this) == true) UseGame(dialog.FileName);
    }

    void UseGame(string path)
    {
        game = path;
        gameOk = false;
        BuildButton.IsEnabled = false;
        DropTitle.Text = Path.GetFileName(path.TrimEnd('\\', '/')) is { Length: > 0 } n ? n : path;
        DropSub.Text = Directory.Exists(path) ? "folder" : "file";
        SetStatus(0, "Checking your game…");
        steps[0].State = 1;
        steps[0].Sub = "Checking…";
        if (tools == null) return;
        checker?.Cancel();
        var mine = checker = new Runner(tools, ["--check", "--game", path]);
        string? verdict = null;
        mine.Line += line =>
        {
            if (line.StartsWith("@@check ")) verdict = line[8..];
        };
        mine.Finished += why => Dispatcher.Invoke(() =>
        {
            if (mine != checker || why == "cancelled") return;
            if (verdict != null && verdict.StartsWith("ok "))
            {
                gameOk = true;
                SetStatus(1, verdict[3..]);
                steps[0].State = 2;
                steps[0].Sub = "Found";
            }
            else
            {
                SetStatus(2, verdict != null && verdict.StartsWith("bad ") ? verdict[4..] : why ?? "This isn't the game.");
                steps[0].State = 0;
                steps[0].Sub = "Choose your copy";
            }
            BuildButton.IsEnabled = gameOk && tools != null;
        });
        mine.Start();
    }

    /// 0 waiting, 1 good, 2 problem
    void SetStatus(int kind, string text)
    {
        StatusText.Text = text;
        StatusDot.Fill = new SolidColorBrush(kind == 1 ? Color.FromRgb(0x4C, 0xB8, 0x80) : kind == 2 ? Color.FromRgb(0xE0, 0x5A, 0x64) : Color.FromRgb(0x7C, 0x8A, 0xA0));
        StatusIcon.Data = Geometry.Parse(kind == 1 ? "M0,6 L4,10 L11,1" : kind == 2 ? "M1,1 L10,10 M10,1 L1,10" : "M1,5.5 L10,5.5");
        StatusPill.BorderBrush = new SolidColorBrush(kind == 1 ? Color.FromArgb(0xB0, 0x9A, 0xF0, 0xC0) : kind == 2 ? Color.FromArgb(0xB0, 0xFF, 0x9A, 0xA2) : Color.FromArgb(0x38, 0xFF, 0xFF, 0xFF));
    }

    void ChangeOut_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog { Title = "Choose where Wondershot goes" };
        if (dialog.ShowDialog(this) != true) return;
        outDir = InstallFolder(dialog.FolderName);
        OutText.Text = outDir;
        RefreshWorkspacePath();
        RefreshInstalled();
    }

    static string InstallFolder(string selected)
    {
        if (!Directory.Exists(selected) || File.Exists(Path.Combine(selected, "wonder.exe"))) return selected;
        // A first build may have stopped after creating its workspace. Reuse that install folder on retry.
        var workspace = Path.Combine(selected, WorkspaceDirectory);
        if (Directory.EnumerateFileSystemEntries(selected).Any(entry =>
            !string.Equals(entry, workspace, StringComparison.OrdinalIgnoreCase) || !Directory.Exists(entry)))
            return Path.Combine(selected, "Wondershot");
        return selected;
    }

    string? BuildWorkspace() => PortableWorkspace.IsChecked == true ? Path.Combine(outDir, WorkspaceDirectory) : null;

    void RefreshWorkspacePath()
    {
        var path = BuildWorkspace() ?? AppDataWorkspace;
        WorkspaceText.Text = path;
        WorkspaceText.ToolTip = path;
    }

    void PortableWorkspace_Click(object sender, RoutedEventArgs e)
    {
        RefreshWorkspacePath();
        SaveSettings();
    }

    void SaveSettings()
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(SettingsPath)!);
            File.WriteAllText(SettingsPath, JsonSerializer.Serialize(new Settings(
                game, outDir, FilesCopy.IsChecked == true, PortableWorkspace.IsChecked == true)));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
    }

    // ---- the build ----
    void Page(string which)
    {
        SetupPage.Visibility = which == "setup" ? Visibility.Visible : Visibility.Collapsed;
        BuildPage.Visibility = which == "build" ? Visibility.Visible : Visibility.Collapsed;
        DonePage.Visibility = which == "done" ? Visibility.Visible : Visibility.Collapsed;
        ErrorPage.Visibility = which == "error" ? Visibility.Visible : Visibility.Collapsed;
    }

    void ShowStepsFor(string which)
    {
        if (which == "setup") { steps[1].State = steps[2].State = steps[3].State = 0; steps[1].Sub = "Compiler and libraries"; steps[2].Sub = "Recompile the game"; steps[3].Sub = "All set"; }
        Page(which);
    }

    void Build_Click(object sender, RoutedEventArgs e) => StartBuild();

    void StartBuild(params string[] extra)
    {
        if (tools == null || game == null || !gameOk || updatingBuilder) return;
        var copy = FilesCopy.IsChecked == true;
        var work = BuildWorkspace();
        var args = new List<string> { "--game", game, "--out", outDir, "--game-files", copy ? "copy" : "link" };
        if (work != null) args.AddRange(["--work", work]);
        args.AddRange(extra);
        SaveSettings();
        log.Clear();
        OpenLogFile(work ?? AppDataWorkspace);
        buildWarning = null;
        LogBox.Clear();
        Bar.Value = 0;
        BarPercent.Text = "0%";
        BarEta.Text = "";
        BuildTitle.Text = "Starting…";
        BuildSub.Text = "Getting things ready";
        steps[1].State = 1; steps[1].Sub = "Starting…"; steps[2].State = 0; steps[3].State = 0;
        building = true;
        Page("build");
        var mine = runner = new Runner(tools, args);
        mine.Line += line => Dispatcher.BeginInvoke(() => OnLine(line));
        mine.Finished += why => Dispatcher.BeginInvoke(() => OnFinished(why));
        mine.Start();
    }

    /// A file for this build's log, the last ten kept: what a player sends when a build stops
    void OpenLogFile(string work)
    {
        CloseLogFile();
        logPath = null;
        try
        {
            Directory.CreateDirectory(LogsDir);
            foreach (var old in new DirectoryInfo(LogsDir).GetFiles("build-*.log").OrderByDescending(f => f.Name).Skip(9))
                try { old.Delete(); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            logPath = Path.Combine(LogsDir, $"build-{DateTime.Now:yyyyMMdd-HHmmss}.log");
            logFile = new StreamWriter(new FileStream(logPath, FileMode.Create, FileAccess.Write, FileShare.ReadWrite), new UTF8Encoding(false)) { AutoFlush = true };
            logFile.WriteLine($"Wondershot Builder {typeof(MainWindow).Assembly.GetName().Version?.ToString(3)}, {DateTime.Now:s}");
            logFile.WriteLine($"game: {game}");
            logFile.WriteLine($"out: {outDir}");
            logFile.WriteLine($"work: {work}");
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { logFile = null; logPath = null; }
    }

    void CloseLogFile()
    {
        try { logFile?.Dispose(); } catch (IOException) { }
        logFile = null;
    }

    void OnLine(string line)
    {
        log.AppendLine(line);
        try { if (!line.StartsWith("@@progress ") && !line.StartsWith("@@eta ")) logFile?.WriteLine(line); } catch (IOException) { }
        if (line.StartsWith("@@stage "))
        {
            var rest = line[8..];
            var sp = rest.IndexOf(' ');
            var id = sp < 0 ? rest : rest[..sp];
            var text = sp < 0 ? "" : rest[(sp + 1)..];
            BuildTitle.Text = text.Length > 0 ? text : id;
            BuildSub.Text = id switch
            {
                "update" => "Fetching the new release's sources from GitHub.",
                "tools" => "Fetching the compiler and libraries the first time (a few hundred MB).",
                "dump" => "Reading your game's files. They stay on your PC.",
                "lift" => "Translating the game's code. This is the long part.",
                "compile" => "Compiling it for your PC.",
                "files" => "Copying your game's romfs and dlc into the folder. A few minutes, and several GB.",
                "layer" => "Your dump keeps the Switch 2 Edition's files in its add-on: they go over the romfs in the game folder. Your dump is not changed.",
                "assemble" => "Putting the game folder together.",
                "hdr" => "Making the HDR shaders from your game: it opens by itself for a moment, then closes.",
                _ => "",
            };
            var step = id == "tools" || id == "update" ? 1 : id == "finish" ? 3 : 2;
            for (var i = 1; i < 4; i++) steps[i].State = i < step ? 2 : i == step ? 1 : 0;
            if (step == 1) steps[1].Sub = text; else { steps[1].Sub = "Ready"; if (step == 2) steps[2].Sub = text; }
        }
        else if (line.StartsWith("@@progress ") && double.TryParse(line[11..], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var p))
        {
            Bar.Value = Math.Clamp(p, 0, 1);
            BarPercent.Text = $"{Math.Round(Bar.Value * 100)}%";
        }
        else if (line.StartsWith("@@eta ") && double.TryParse(line[6..], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var s))
        {
            BarEta.Text = s < 90 ? "about a minute left" : $"about {Math.Round(s / 60)} minutes left";
        }
        else if (line.StartsWith("@@done "))
        {
            builtFolder = line[7..].Trim();
        }
        else if (line.StartsWith("@@warn "))
        {
            buildWarning = line[7..].Trim();
        }
        if (!line.StartsWith("@@progress ") && !line.StartsWith("@@eta "))
        {
            LogBox.AppendText(line + Environment.NewLine);
            LogBox.ScrollToEnd();
        }
    }

    void OnFinished(string? why)
    {
        building = false;
        try { if (why != null && why != "cancelled") logFile?.WriteLine("-- stopped: " + why); } catch (IOException) { }
        CloseLogFile();
        if (why == "cancelled") { ShowStepsFor("setup"); steps[0].State = gameOk ? 2 : 0; return; }
        if (why != null)
        {
            ErrorBox.Text = logPath == null ? why : why + "\n\nThe full log is saved at:\n" + logPath;
            for (var i = 1; i < 4; i++) if (steps[i].State == 1) steps[i].State = 0;
            Page("error");
            return;
        }
        builtFolder ??= outDir;
        if (updateTag != null) { updateTag = updateUrl = null; UpdatePill.Visibility = Visibility.Collapsed; }   // (the release is in)
        RefreshInstalled();
        for (var i = 0; i < 4; i++) steps[i].State = 2;
        steps[2].Sub = "Built";
        steps[3].Sub = "Ready";
        DoneWarn.Visibility = string.IsNullOrEmpty(buildWarning) ? Visibility.Collapsed : Visibility.Visible;
        DoneWarnText.Text = buildWarning ?? "";
        DoneText.Text = "Wondershot is in " + builtFolder + ". Plug in a controller if you like: every pad, and the keyboard, can be a player.";
        Page("done");
    }

    void Cancel_Click(object sender, RoutedEventArgs e) => runner?.Cancel();
    void Back_Click(object sender, RoutedEventArgs e) { ShowStepsFor("setup"); steps[0].State = gameOk ? 2 : 0; }
    void Again_Click(object sender, RoutedEventArgs e) { ShowStepsFor("setup"); steps[0].State = gameOk ? 2 : 0; }
    void OpenLogs_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            Directory.CreateDirectory(LogsDir);
            if (logPath != null && File.Exists(logPath)) Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{logPath}\"") { UseShellExecute = true });
            else Process.Start(new ProcessStartInfo(LogsDir) { UseShellExecute = true });
        }
        catch (Exception ex) when (ex is IOException or System.ComponentModel.Win32Exception) { }
    }
    void CopyLog_Click(object sender, RoutedEventArgs e)
    {
        try { Clipboard.SetText(ErrorBox.Text + Environment.NewLine + Environment.NewLine + log); } catch (System.Runtime.InteropServices.ExternalException) { }
    }

    // ---- an install that is already there, and a newer release of the port ----
    /// What a Wondershot folder says about itself (wondershot_version.txt, written when it was built): version, built, game
    Dictionary<string, string>? ReadStamp(string folder)
    {
        try
        {
            var path = Path.Combine(folder, "wondershot_version.txt");
            if (!File.Exists(path) || !File.Exists(Path.Combine(folder, "wonder.exe"))) return null;
            var map = new Dictionary<string, string>();
            foreach (var line in File.ReadAllLines(path))
                if (line.IndexOf('=') is var at and > 0) map[line[..at]] = line[(at + 1)..].Trim();
            return map;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
    }

    /// The install folder holds a Wondershot: say so, offer Play, and make the button an Update (the same build, from the game it
    /// was made from, with the compiler's work kept: only what changed is compiled again)
    void RefreshInstalled()
    {
        var stamp = ReadStamp(outDir);
        InstalledStrip.Visibility = stamp != null ? Visibility.Visible : Visibility.Collapsed;
        BuildButton.Content = stamp != null ? "UPDATE WONDERSHOT" : "BUILD WONDERSHOT";
        BuildHint.Text = stamp != null ? "Updating builds again from the same game, and only recompiles what changed: it is quick. Press Play to start the game."
                                       : "The first build takes a while (your PC recompiles the whole game, and fetches the build tools once). After that, just press Play.";
        if (stamp == null) return;
        stamp.TryGetValue("version", out var version);
        stamp.TryGetValue("built", out var built);
        InstalledTitle.Text = "Wondershot is installed here";
        InstalledSub.Text = $"Release {(string.IsNullOrEmpty(version) || version == "dev" ? "from source" : version)}" + (string.IsNullOrEmpty(built) ? "" : $" · built {built}");
        // (no game chosen yet: the one this folder was built from, when it is still where it was)
        if (game == null && stamp.TryGetValue("game", out var g) && !string.IsNullOrWhiteSpace(g) && (Directory.Exists(g) || File.Exists(g)))
            UseGame(g);
    }

    void PlaySetup_Click(object sender, RoutedEventArgs e) { builtFolder = outDir; Play_Click(sender, e); }
    void GameSettingsSetup_Click(object sender, RoutedEventArgs e) { builtFolder = outDir; GameSettings_Click(sender, e); }

    /// Asks GitHub (through the build script, which knows the release the sources are) whether the port has a newer release
    void CheckForUpdate()
    {
        if (tools == null) return;
        var asker = new Runner(tools, ["--check-update"]);
        string? answer = null, builderTag = null;
        asker.Line += line =>
        {
            if (line.StartsWith("@@update ")) answer = line[9..];
            else if (line.StartsWith("@@builder-update ")) builderTag = line[17..];
        };
        asker.Finished += _ => Dispatcher.BeginInvoke(() =>
        {
            if (builderTag != null)
            {
                builderUpdateTag = builderTag;
                BuilderUpdateButton.ToolTip = $"Update Wondershot Builder to {builderTag} and reopen it.";
                BuilderUpdateButton.Visibility = Visibility.Visible;
            }
            if (answer == null || !answer.StartsWith("available ")) return;
            var parts = answer.Split(' ', 3);
            if (parts.Length < 3) return;
            updateTag = parts[1];
            updateUrl = parts[2];
            UpdateTitle.Text = $"Wondershot {updateTag} is out";
            UpdateSub.Text = RefreshedFolderIsInstalled() ? "Click to update your install" : "Click to build this release";
            UpdatePill.Visibility = Visibility.Visible;
        });
        asker.Start();
    }

    bool RefreshedFolderIsInstalled() => ReadStamp(outDir) != null;

    void UpdatePill_Click(object sender, MouseButtonEventArgs e)
    {
        if (building || updatingBuilder || updateTag == null || updateUrl == null) return;
        if (!gameOk || game == null)
        {
            MessageBox.Show(this, $"Wondershot {updateTag} is ready to download. Choose your game first, then click this again: the update downloads the new release and rebuilds only what changed.",
                            "Wondershot Builder", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }
        StartBuild("--update-to", updateTag, "--update-url", updateUrl);
    }

    void BuilderUpdate_Click(object sender, RoutedEventArgs e)
    {
        if (tools == null || builderUpdateTag == null || building || updatingBuilder) return;
        updatingBuilder = true;
        SetupPage.IsEnabled = false;
        BuilderUpdateButton.IsEnabled = false;
        BuilderUpdateButton.Content = "Updating Builder…";
        SaveSettings();
        var updater = new Runner(tools, ["--update-builder", builderUpdateTag]);
        string? exe = null;
        updater.Line += line => { if (line.StartsWith("@@builder-ready ")) exe = line[16..]; };
        updater.Finished += why => Dispatcher.BeginInvoke(() =>
        {
            if (why == null && exe != null)
            {
                try
                {
                    BuilderUpdate.Start(exe, AppContext.BaseDirectory);
                    Close();
                    return;
                }
                catch (Exception ex) when (ex is IOException or Win32Exception) { why = ex.Message; }
            }
            updatingBuilder = false;
            SetupPage.IsEnabled = true;
            BuilderUpdateButton.IsEnabled = true;
            BuilderUpdateButton.Content = "Update Builder app";
            MessageBox.Show(this, why ?? "The update did not return a Builder to open.", "Wondershot Builder",
                            MessageBoxButton.OK, MessageBoxImage.Error);
        });
        updater.Start();
    }

    void Play_Click(object sender, RoutedEventArgs e) => Launch(false);

    /// The game's settings are its Insert menu, which a key opens in the game: this starts the game with it open already
    /// (WONDER_MENU_AT_START, read by the renderer's menu), so they can be set without going through the title first
    void GameSettings_Click(object sender, RoutedEventArgs e) => Launch(true);

    void Launch(bool openMenu)
    {
        var folder = builtFolder ?? outDir;
        var exe = Path.Combine(folder, "wonder.exe");
        if (!File.Exists(exe)) { MessageBox.Show(this, "wonder.exe is not in " + folder, "Wondershot Builder"); return; }
        var psi = new ProcessStartInfo(exe) { WorkingDirectory = folder, UseShellExecute = false };
        if (openMenu) psi.Environment["WONDER_MENU_AT_START"] = "1";
        Process.Start(psi);
    }

    void OpenFolder_Click(object sender, RoutedEventArgs e)
    {
        var folder = builtFolder ?? outDir;
        if (Directory.Exists(folder)) Process.Start(new ProcessStartInfo("explorer.exe", $"\"{folder}\"") { UseShellExecute = true });
    }
}
