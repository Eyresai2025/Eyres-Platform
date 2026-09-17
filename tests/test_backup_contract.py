import tempfile, unittest, zipfile
from pathlib import Path
from tools.backup_restore import digest, inspect_backup
import json
class BackupTests(unittest.TestCase):
 def test_checksum_verification_and_tamper_detection(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"b.zip"; data=b'{"x":1}\n'; m={"format":1,"collections":{"x":1},"files":{"collections/x.jsonl":digest(data)}}
   with zipfile.ZipFile(p,"w") as z: z.writestr("collections/x.jsonl",data); z.writestr("manifest.json",json.dumps(m))
   self.assertEqual(inspect_backup(p)["format"],1)
   with zipfile.ZipFile(p,"w") as z: z.writestr("collections/x.jsonl",b"changed"); z.writestr("manifest.json",json.dumps(m))
   with self.assertRaises(ValueError): inspect_backup(p)
if __name__=="__main__": unittest.main()
