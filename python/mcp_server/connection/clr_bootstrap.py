"""pythonnet runtime selection and loading the EPLAN Remote Client DLLs."""

import os
import sys

from connection.logs import logger
from connection.versions import PLATFORM_ROOT, detect_installed_versions


def _select_dotnet_runtime(runtime: str) -> None:
    """Select the pythonnet runtime. Must run before the first `import clr`
    and can only happen once per process — switching afterwards requires
    restarting the MCP server."""
    try:
        from pythonnet import load as _pnet_load
        if runtime == "coreclr":
            _pnet_load("coreclr")
            logger.info("pythonnet: coreclr (.NET 8) runtime selected (EPLAN 2027+)")
        else:
            logger.info("pythonnet: using default runtime (EPLAN 2026 or older)")
    except Exception as _pnet_err:
        logger.warning(f"pythonnet: runtime selection failed ({_pnet_err})")


class ClrBootstrapMixin:
    def _setup_api(self) -> bool:
        """Load EPLAN DLLs via pythonnet."""
        try:
            installs = detect_installed_versions()
            if not installs:
                self.last_error = f"No EPLAN installation found under {PLATFORM_ROOT}"
                logger.error(self.last_error)
                return False

            if self.target_version:
                chosen = next((i for i in installs if i["version"] == self.target_version), None)
                if chosen is None:
                    available = ", ".join(i["version"] for i in installs)
                    self.last_error = f"EPLAN {self.target_version} not installed (available: {available})"
                    logger.error(self.last_error)
                    return False
            else:
                chosen = installs[0]
                logger.info(f"Auto-detected EPLAN {chosen['full_version']} (newest installed)")

            self.target_version = chosen["version"]
            _select_dotnet_runtime(chosen["runtime"])

            import clr

            eplan_path = chosen["bin"]

            if eplan_path not in sys.path:
                sys.path.append(eplan_path)

            # Add additional dependency paths
            dep_paths = [
                r"C:\Program Files\EPLAN\Common\IdentityClient",
                os.path.join(os.path.dirname(eplan_path), "Bin"),
            ]
            for dp in dep_paths:
                if os.path.exists(dp) and dp not in sys.path:
                    sys.path.append(dp)

            # Load EPLAN DLLs via LoadFrom so .NET probes the EPLAN Bin directory
            # for dependencies (e.g. Grpc.Core), preventing version conflicts with
            # any system-wide or Python-env assembly of the same name.
            import System.Reflection
            import System

            # The Remote Client writes chatter ("Server response: Hello ...")
            # through .NET Console.Out, i.e. the process stdout that the MCP
            # stdio transport owns; every such line is a corrupt JSON-RPC
            # message to the client. Send .NET console output to stderr.
            System.Console.SetOut(System.Console.Error)

            def _resolve_from_eplan(sender, args):
                asm_name = System.Reflection.AssemblyName(args.Name).Name
                candidate = os.path.join(eplan_path, asm_name + ".dll")
                if os.path.exists(candidate):
                    return System.Reflection.Assembly.LoadFrom(candidate)
                return None

            System.AppDomain.CurrentDomain.AssemblyResolve += _resolve_from_eplan

            for dll in ("Eplan.EplApi.Starteru.dll", "Eplan.EplApi.RemoteClientu.dll", "Eplan.EplApi.Remotingu.dll"):
                dll_path = os.path.join(eplan_path, dll)
                if os.path.exists(dll_path):
                    System.Reflection.Assembly.LoadFrom(dll_path)

            clr.AddReference("Eplan.EplApi.Starteru")
            clr.AddReference("Eplan.EplApi.RemoteClientu")
            clr.AddReference("Eplan.EplApi.Remotingu")

            logger.info(f"EPLAN API loaded from: {eplan_path}")
            return True

        except ImportError:
            self.last_error = "pythonnet not installed. Run: pip install pythonnet"
            logger.error(self.last_error)
            return False
        except Exception as e:
            self.last_error = f"Failed to load EPLAN API: {e}"
            logger.error(self.last_error)
            return False
