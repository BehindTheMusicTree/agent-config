#!/usr/bin/env python3
"""Validate plugin manifests, shared skills, and their local dependencies."""
import json
import re
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else Path(__file__).resolve().parent.parent
errors = []
manifests = {}
for file in (root / '.claude-plugin').glob('*.json'):
    try:
        manifests[file.name] = json.loads(file.read_text())
    except ValueError as exc:
        errors.append(f'{file}: {exc}')
plugin = manifests.get('plugin.json', {})
marketplace = manifests.get('marketplace.json', {})
if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', str(plugin.get('version', ''))):
    errors.append('Plugin version must be a stable semantic version')
if not any(entry.get('name') == plugin.get('name') for entry in marketplace.get('plugins', []) if isinstance(entry, dict)):
    errors.append('Marketplace must include the plugin manifest name')
commands = {file.stem for file in (root / 'commands').glob('*.md')}
skills = {file.parent.name for file in (root / 'skills').glob('*/SKILL.md')}
if commands != skills:
    errors.append(f'Command/skill mismatch: Claude-only={sorted(commands - skills)}, Codex-only={sorted(skills - commands)}')
for file in (root / 'skills').glob('*/SKILL.md'):
    content = file.read_text()
    match = re.match(r'^---\n(.*?)\n---\n', content, re.S)
    if not match:
        errors.append(f'{file}: missing frontmatter')
        continue
    try:
        meta = yaml.safe_load(match.group(1))
        name = meta.get('name') if isinstance(meta, dict) else None
        description = meta.get('description') if isinstance(meta, dict) else None
        if not isinstance(name, str) or name != file.parent.name or len(name) > 64 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
            errors.append(f'{file}: invalid skill name')
        if not isinstance(description, str) or not description.strip() or len(description) > 1024:
            errors.append(f'{file}: invalid description')
        if isinstance(meta, dict) and set(meta) - {'name', 'description', 'license', 'allowed-tools', 'metadata'}:
            errors.append(f'{file}: unsupported frontmatter fields')
    except yaml.YAMLError as exc:
        errors.append(f'{file}: {exc}')
    for script in re.findall(r'\$SKILL_REPO_ROOT/scripts/([\w.-]+)', content):
        if not (root / 'scripts' / script).is_file():
            errors.append(f'{file}: missing script {script}')
    for target in re.findall(r'`\$([a-z][a-z0-9-]*)(?=[ `])', content):
        if target not in skills:
            errors.append(f'{file}: missing skill {target}')
for file in (root / 'commands').glob('*.md'):
    content = file.read_text()
    for target in re.findall(r'agent-config:([a-z][a-z0-9-]*)', content):
        if target not in commands:
            errors.append(f'{file}: missing command {target}')
    for script in re.findall(r'\$\{CLAUDE_PLUGIN_ROOT\}/scripts/([\w.-]+)', content):
        if not (root / 'scripts' / script).is_file():
            errors.append(f'{file}: missing script {script}')
for file in [*(root / 'commands').glob('*.md'), *(root / 'skills').glob('*/SKILL.md')]:
    for reference in re.findall(r'(?:\$SKILL_REPO_ROOT|\$\{CLAUDE_PLUGIN_ROOT\})/references/([\w./-]+)', file.read_text()):
        target = root / 'references' / reference
        if not target.is_relative_to(root / 'references') or '..' in Path(reference).parts or not target.is_file():
            errors.append(f'{file}: missing or invalid reference {reference}')
if errors:
    raise SystemExit('\n'.join(errors))
print('Manifests, commands, skills, and local references validated')
