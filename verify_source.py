"""Verify the complete listed release source offline."""

import ast
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = "SHA256_MANIFEST.json"


def main():
    try:
        manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        if manifest["version"] != "1.07" or manifest["algorithm"] != "SHA-256":
            raise ValueError("Unsupported source manifest")
        sources = manifest["files"]
        if not sources:
            raise ValueError("Empty source manifest")
        for name, digest in sorted(sources.items()):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid source path")
            path = ROOT / relative
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                raise ValueError("Unexpected symbolic link")
            contents = path.read_bytes()
            if sha256(contents).hexdigest() != digest:
                raise ValueError(f"Source checksum mismatch in {name}")
            if path.suffix == ".py":
                ast.parse(contents, filename=name, feature_version=(3, 11))
                compile(contents, name, "exec")
        for folder in ("coincat", "research"):
            actual = {path.relative_to(ROOT).as_posix() for path in (ROOT / folder).rglob("*.py")}
            if actual != {name for name in sources if name.startswith(folder + "/") and name.endswith(".py")}:
                raise ValueError(f"Unexpected Python source in {folder}")
    except (OSError, KeyError, SyntaxError, TypeError, ValueError) as error:
        print(f"Source verification failed. {error}")
        return 1
    print(f"CoinCat v1.07 source verified. {len(sources)} SHA-256 hashes matched and Python files compiled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
