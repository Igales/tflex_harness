using System;
using TFlex;

public class Program
{
    public static int Main()
    {
        var setup = new ApplicationSessionSetup();
        setup.ReadOnly = true;
        setup.Enable3D = false;
        setup.EnableDOCs = false;
        setup.EnableMacros = false;
        setup.PromptToSaveModifiedDocuments = false;
        setup.ProtectionLicense = ApplicationSessionSetup.License.TFlexAPI;

        Console.WriteLine("Starting API initialization");

        bool initialized = Application.InitSession(setup);
        Console.WriteLine("init=" + initialized);

        if (!initialized)
            return 3;

        try
        {
            Console.WriteLine("API session initialized");
            return 0;
        }
        finally
        {
            Application.ExitSession();
            Console.WriteLine("ExitSession completed");
        }
    }
}
