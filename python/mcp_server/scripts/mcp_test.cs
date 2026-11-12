using System.Windows.Forms;
using Eplan.EplApi.Scripting;

public class MCPTest
{
    [Start]
    public void Run()
    {
        MessageBox.Show(
            "MCP Connection OK!",
            "EPLAN MCP Server",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information
        );
    }
}
