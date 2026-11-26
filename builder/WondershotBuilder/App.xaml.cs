using System.Windows;

namespace WondershotBuilder;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        BuilderUpdate.Cleanup(e.Args);
        base.OnStartup(e);
    }
}
