using System;
using TFlex;

public class Program
{
    public static int Main()
    {
        var setup = new ApplicationSessionSetup();
        setup.ReadOnly = false;
        setup.Enable3D = true;
        setup.EnableDOCs = false;
        setup.EnableMacros = false;
        setup.PromptToSaveModifiedDocuments = false;
        setup.ProtectionLicense = ApplicationSessionSetup.License.TFlex3D;

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

