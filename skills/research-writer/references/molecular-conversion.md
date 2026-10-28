# Independently checked local molecular conversion

The optional original MIT adapter `scripts/conversion_tools.py` executes a
user-selected Open Babel executable, then checks every molecule with a separate
RDKit parser. Open Babel itself remains GPL-2.0-only; no binary, library or source
is bundled or relicensed by this skill. Install a compatible engine in a separate
runtime or reuse your own executable. The adapter's interpreter needs RDKit;
the engine executable can belong to another environment.

```sh
python PATH_TO_SKILL/scripts/conversion_tools.py convert --executable PATH_TO_OBABEL --input PROJECT/input.smi --input-format smi --output PROJECT/output.sdf --output-format sdf --report PROJECT/conversion.json
```

The selected interpreter must actually contain RDKit. A profile declaration does
not switch interpreters, probe another device or install software. On Windows use
the actual compatible executable/launcher path; do not paste a shell command into
`--executable`. This route uses CPU conversion, no GPU, network or model weights.

Only explicit SMILES (`smi`) and SDF (`sdf`) inputs/outputs are accepted. Input is
bounded to 10 MiB and 32 molecules. SDF records need `$$$$` terminators. Invalid
records fail before execution. Each output must retain molecule count and order,
canonical isomeric SMILES, formula, charge, heavy-atom count and bond types under
RDKit. Unsupported/lost specified chirality or double-bond stereochemistry fails;
an engine exit of zero or a reported conversion count is insufficient.

SMILES-to-SDF conversion generates a **2D depiction** using a fixed Open Babel
option so standard stereochemical representation survives independent parsing.
Without it Open Babel can store stereo in its own zero-coordinate extension,
which this independent reader cannot validate. No 3D geometry, pose, original
coordinate, molecule-property, title or annotation preservation is promised.
Coordinate-bearing input can still lose information outside the identity checks.
Use a separately validated workflow when those fields matter.

The default engine timeout is 30 seconds and must be at most 120 seconds.
Version and engine subprocesses use fixed argument arrays and no shell. Temporary
conversion output and logs are watched for size limits. Successful output is
published only after independent identity validation; failed runs retain report
details and logs. Existing molecular/report files are preserved unless explicit
`--force` is supplied. The report records input/output hashes, executable hash,
version response, actual arguments, Python/RDKit/platform and limits. An executable
hash does not authenticate all linked libraries or its complete environment.

Conversion checks demonstrate local execution and identity consistency, not
physical accuracy, docking quality, affinity, biological function or safety. No
benchmark-performance claim follows from successful conversion.

Official references: [CLI options](https://openbabel.org/docs/Command-line_tools/babel.html),
[stereochemistry](https://openbabel.org/docs/Stereochemistry/stereo.html),
[official Python package and rights](https://pypi.org/project/openbabel/3.2.1/),
[upstream license](https://github.com/openbabel/openbabel/blob/master/COPYING).
