"""Package a new staged draft for macOS Jianying without replacing user edits."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))
import mac_draft


def inspect_source(source):
    with (source / 'draft_content.json').open() as handle:
        content = json.load(handle)
    with (source / 'draft_meta_info.json').open() as handle:
        json.load(handle)
    media = [Path(m['path']) for group in ('videos', 'audios')
             for m in content.get('materials', {}).get(group, [])]
    for path in media:
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f'Media must be an existing absolute file: {path}')
    return {'duration_us': content.get('duration'), 'media_files': len(set(media)),
            'tracks': [{'type': t['type'], 'segments': len(t.get('segments', []))}
                       for t in content.get('tracks', [])]}


def app_running():
    result = subprocess.run(['ps', '-axo', 'comm='], check=True,
                            capture_output=True, text=True)
    return any(Path(line.strip()).name in ('VideoFusion-macOS', 'JianyingPro')
               for line in result.stdout.splitlines())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--name', required=True)
    parser.add_argument('--draft-root', type=Path, default=Path(mac_draft.DRAFT_ROOT))
    parser.add_argument('--install', action='store_true', help='Default is input validation only')
    parser.add_argument('--allow-missing-fingerprint', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise ValueError('This adapter is installed for macOS Jianying only')
    source, root = args.source.resolve(), args.draft_root.expanduser().resolve()
    mac_draft.DRAFT_ROOT = str(root)
    mac_draft.ROOT_META = str(root / 'root_meta_info.json')
    target = Path(mac_draft._validate_draft_name(args.name))
    if source.is_relative_to(root):
        raise ValueError('Source must be external staging, not an existing Jianying draft')
    if target.exists():
        raise FileExistsError(f'Will not replace an existing draft; choose a new name: {target}')
    with Path(mac_draft.ROOT_META).open() as handle:
        registry = json.load(handle)
    if any(e.get('draft_name') == args.name for e in registry.get('all_draft_store', [])):
        raise FileExistsError('Name already registered; choose a new version name')
    report = inspect_source(source)
    report.update({'name': args.name, 'target': str(target), 'installed': False})
    if args.install:
        if app_running():
            raise RuntimeError('Quit Jianying normally through its UI before installing a draft')
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory(prefix='jianying-package-', dir=source.parent) as tmp:
            temp = Path(tmp)
            prepared = temp / 'draft'
            shutil.copytree(source, prepared)
            (temp / 'ffmpeg').symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
            os.environ['PATH'] = str(temp) + os.pathsep + os.environ.get('PATH', '')
            info = mac_draft.macify(str(prepared), args.name,
                                   allow_missing_fingerprint=args.allow_missing_fingerprint)
            # Recheck after preparation: never overwrite an intervening user edit.
            if target.exists() or app_running():
                raise RuntimeError('Draft destination or app state changed; installation stopped')
            backup = mac_draft.install(str(prepared), args.name, info)
            report.update({'installed': True, 'registry_backup': backup,
                           'packaged': inspect_source(target)})
        (source / 'installation-receipt.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
