"""Actual interpreter-startup counterexample; no SDK/tool/device invocation."""
from pathlib import Path
import os,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c07_kotlin_execution import napi_inventory_command

class BinderStartupTests(unittest.TestCase):
    def test_actual_binder_command_ignores_external_site_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);marker=root/'executed.txt'
            (root/'sitecustomize.py').write_text('import os\nfrom pathlib import Path\nPath(os.environ["C07_SITE_SENTINEL"]).write_text("external startup")\n')
            environment=dict(os.environ,PYTHONPATH=str(root),C07_SITE_SENTINEL=str(marker))
            command=list(map(str,napi_inventory_command(sys.executable,root/'contract',root/'bootstrap',root/'provider',root,root/'output')))
            # Same binder executable and args as production; --help needs no ELF/tool.
            red=[arg for arg in command if arg not in ('-I','-S','-B')]+['--help']
            old=subprocess.run(red,env=environment,capture_output=True,timeout=10)
            self.assertEqual(old.returncode,0,old.stderr)
            self.assertTrue(marker.exists(),'negative control did not exercise external Python startup')
            marker.unlink()
            fixed=subprocess.run(command+['--help'],env=environment,capture_output=True,timeout=10)
            self.assertEqual(fixed.returncode,0,fixed.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(command[1:4],['-I','-S','-B'])

if __name__=='__main__':unittest.main()
