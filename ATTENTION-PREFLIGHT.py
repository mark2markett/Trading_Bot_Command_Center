"""Feature-specific source checks plus the existing idle financial-state guard."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def check(root,now=None):
    root=Path(root).resolve()
    manifest_path=Path(__file__).with_name('ATTENTION-NATIVE-SOURCE.json')
    if not manifest_path.exists():
        raise ValueError('Reviewed source manifest is missing')
    manifest=json.loads(manifest_path.read_text())
    spec=importlib.util.spec_from_file_location('attention_idle_guard',Path(__file__).with_name('NATIVE-OCT14-PREFLIGHT.py'))
    guard=importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    guard.TARGETS=tuple(manifest['stages']['installed'])
    guard.SOURCE={'stages':manifest['stages']}
    for name in guard.TARGETS:
        target=root/name
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent!=root and root in parent.parents):
            raise ValueError('Source target is a symbolic link')
    guard.check_git(root)
    return guard.check(root,now)


if __name__=='__main__':
    try:
        print(json.dumps(check(sys.argv[1])))
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)}))
        raise SystemExit(1)
