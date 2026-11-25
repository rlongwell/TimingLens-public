"""Freeze the source inputs of a native, self-contained Vivado project."""
from dataclasses import dataclass
from hashlib import file_digest
import os
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile, TemporaryDirectory
from xml.etree import ElementTree as ET


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class Project:
    xpr: Path
    files: tuple[Path, ...]
    tracked: dict[Path, str]

    @classmethod
    def read(cls, xpr):
        xpr = Path(xpr).absolute()
        if xpr.suffix.lower() != ".xpr" or not xpr.is_file() or xpr.is_symlink():
            raise ValueError("Select a local Vivado .xpr project.")
        root = xpr.parent.resolve()
        xpr = root / xpr.name
        srcs = xpr.stem + ".srcs"
        try:
            xml = ET.parse(xpr)
        except ET.ParseError as error:
            raise ValueError(f"Invalid Vivado project XML: {error}") from error
        files, tracked = [], {Path(xpr.name)}
        for option in xml.findall(".//Option"):
            if option.get("Name", "").upper() in {"PR_FLOW", "PRFLOW", "PRFLOWENABLED"} and option.get("Val", "").lower() in {"1", "true"}:
                raise ValueError("Automatic fixes currently require a static design.")
        # Run hooks, custom flows and external include/IP repositories can change
        # synthesis semantics or execute code outside a staged project.
        for entry in xml.iter():
            for key in ("Name", "Id"):
                prop = entry.get(key, "").upper()
                if ((prop.startswith("STEPS.") and ".TCL." in prop) or
                        prop in {"IPREPOPATHS", "INCLUDEDIRS", "MOREOPTIONS", "TCLPRE", "TCLPOST",
                                 "TCL.PRE", "TCL.POST"}) and (entry.get("Val") or entry.get("Value")):
                    raise ValueError(f"Automatic routing cannot reproduce project setting {prop} in isolation.")
        for fs in xml.findall(".//FileSet"):
            for node in fs.findall("File"):
                raw = node.get("Path", "").replace("$PSRCDIR/", srcs + "/").replace("$PPRDIR/", "")
                path = Path(raw)
                if path.is_absolute():
                    raise ValueError(f"Import this source with a project-relative path before cloning: {raw}")
                path = root / path
                if not path.is_file() or path.resolve() != path or not path.is_relative_to(root):
                    raise ValueError(f"Import the project source locally before automatic implementation: {raw}")
                rel = path.relative_to(root)
                tracked.add(rel)
                if fs.get("Type") in {"DesignSrcs", "Constrs"}:
                    files.append(rel)
        if not files:
            raise ValueError("No native design sources were found in this project.")
        # Associated headers, memories and .bd assets can also affect the implementation.
        for path in (root / srcs).rglob("*"):
            if path.is_symlink():
                raise ValueError(f"Linked project asset cannot be isolated: {path}")
            if path.is_file():
                tracked.add(path.relative_to(root))
        # Vivado reopens block cells from both the .bd and its child .xci.
        # Capture each child as an implementation input in the Lab record.
        bd_folders = [rel.parent for rel in files if rel.suffix.lower() == ".bd"]
        files.extend(rel for rel in tracked if rel.suffix.lower() == ".xci"
                     and any(rel.is_relative_to(folder / "ip") for folder in bd_folders))
        return cls(xpr, tuple(sorted(set(files))), {name: digest(root/name) for name in sorted(tracked)})

    def clone(self, directory):
        directory.mkdir(parents=True, exist_ok=False)
        for rel, expected in self.tracked.items():
            dest = directory / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.xpr.parent / rel, dest)
            if digest(dest) != expected:
                raise ValueError(f"Project input changed during copy: {rel}")
        return directory / self.xpr.name

    def publish(self, rel, data, backup):
        import fcntl
        if rel not in self.files or rel.suffix.lower() not in {".sv", ".v", ".bd"}:
            raise ValueError("Only an authored, validated source file can be published.")
        root = self.xpr.parent
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if Project.read(self.xpr).tracked != self.tracked:
                raise ValueError("Project inputs changed during the experiment. The candidate is retained for review.")
            original = root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            with backup.open("xb") as stream:
                stream.write(original.read_bytes())
            with NamedTemporaryFile(dir=original.parent, delete=False) as stream:
                tmp = Path(stream.name)
                try:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.fchmod(stream.fileno(), original.stat().st_mode & 0o777)
                    if digest(original) != self.tracked[rel]:
                        raise ValueError("The target changed before publication.")
                    os.replace(tmp, original)
                finally:
                    tmp.unlink(missing_ok=True)
        finally:
            os.close(fd)


    def publish_block(self, bd, xci, payload, backup):
        """Exchange the complete BD directory atomically on the local Linux filesystem."""
        import ctypes
        import fcntl

        if (bd.suffix != ".bd" or xci.suffix != ".xci" or not xci.is_relative_to(bd.parent / "ip")
                or set(payload) != {bd, xci} or not set(payload) <= set(self.files)):
            raise ValueError("The verified block edit requires a matching BD and child XCI.")
        if not bd.parent.parts or not bd.parent.is_relative_to(self.xpr.with_suffix(".srcs").name):
            raise ValueError("In-place publication requires a dedicated block directory in the native source set.")
        root = self.xpr.parent
        original = root / bd.parent
        exchange = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
        if not exchange:
            raise ValueError("This filesystem requires manual publication of the verified block design.")
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if Project.read(self.xpr).tracked != self.tracked:
                raise ValueError("Project inputs changed during the experiment.")
            with TemporaryDirectory(dir=root) as stage:
                prepared = Path(stage) / "block"
                shutil.copytree(original, prepared)
                for rel, data in payload.items():
                    saved = backup / rel
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    with saved.open("xb") as stream:
                        stream.write((root / rel).read_bytes())
                    (prepared / rel.relative_to(bd.parent)).write_bytes(data)
                if Project.read(self.xpr).tracked != self.tracked:
                    raise ValueError("Project inputs changed before publication.")
                # RENAME_EXCHANGE preserves the visibility of both files as a pair.
                if exchange(-100, os.fsencode(original), -100, os.fsencode(prepared), 2):
                    error = ctypes.get_errno()
                    raise OSError(error, os.strerror(error))
        finally:
            os.close(fd)
