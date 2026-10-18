#!/usr/bin/env python3
"""Read-only, fail-closed integrity check; never deploys an automation."""
import hashlib
import json
import re
import sys

ID = '6a825a73808c81918c5c7b5d1fecaf28'
REQUIRED_KEYS = ('TerminalizerNativeProtocol', 'TerminalizerSourceRepository',
                 'TerminalizerSourceCommit', 'TerminalizerPythonSHA256',
                 'GovernanceSuccessorHandoff', 'NextConfigExecutableHandoff',
                 'H9SecondaryBaselineReadRoute')
UNCHANGED = ('id', 'schedule', 'is_enabled', 'timing_mode',
             'notifications_enabled', 'email_enabled')
MARKER = '---BOOTSTRAP_BODY---\n'
HEX64 = re.compile(r'[0-9a-f]{64}\Z')

def split_prompt(prompt):
    normalized = prompt.replace('\r\n', '\n')
    if normalized.count(MARKER) != 1 or normalized.count('---BOOTSTRAP_BODY---') != 1:
        raise ValueError('MISSING_OR_DUPLICATED_MARKER')
    envelope, body = normalized.split(MARKER, 1)
    if body.endswith('\n'):
        body = body[:-1]
    return envelope, body

def sha_body(prompt):
    return hashlib.sha256(split_prompt(prompt)[1].encode('utf-8')).hexdigest()

def envelope_values(envelope, issues, prefix):
    items = {}
    for line in envelope.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in items:
            issues.append(prefix + 'DUPLICATE_KEY_' + key)
        items[key] = value
    for key in (*REQUIRED_KEYS, 'BootstrapBodySHA256'):
        value = items.get(key, '')
        if not value.strip():
            issues.append(prefix + 'EMPTY_OR_MISSING_' + key)
    for key in ('BootstrapBodySHA256', 'TerminalizerPythonSHA256'):
        if key in items and not HEX64.fullmatch(items[key]):
            issues.append(prefix + 'INVALID_SHA_' + key)
    return items

def check(before, proposed):
    issues = []
    if before.get('id') != ID or proposed.get('id') != ID:
        issues.append('WRONG_TASK_ID')
    for field in UNCHANGED:
        if field not in before or field not in proposed:
            issues.append('MISSING_FIELD_' + field)
        elif before[field] != proposed[field]:
            issues.append('UNAUTHORIZED_CHANGE_' + field)
    old, new = before.get('prompt'), proposed.get('prompt')
    if not isinstance(old, str) or not isinstance(new, str):
        return issues + ['PROMPT_NOT_STRING']
    if len(new.encode('utf-8')) < len(old.encode('utf-8')):
        issues.append('PROMPT_LENGTH_REGRESSION')
    try:
        old_env, old_body = split_prompt(old)
        new_env, new_body = split_prompt(new)
        old_fields = envelope_values(old_env, issues, 'ORIGINAL_')
        new_fields = envelope_values(new_env, issues, 'PROPOSED_')
        if old_body != new_body:
            issues.append('IMMUTABLE_BODY_CHANGED')
        for label, fields, body in (('ORIGINAL_', old_fields, old_body),
                                    ('PROPOSED_', new_fields, new_body)):
            if fields.get('BootstrapBodySHA256') != hashlib.sha256(body.encode('utf-8')).hexdigest():
                issues.append(label + 'BOOTSTRAP_SHA_MISMATCH')
        for key in REQUIRED_KEYS:
            if key in old_fields and new_fields.get(key) != old_fields[key]:
                issues.append('PROTECTED_FIELD_CHANGED_' + key)
    except ValueError as exc:
        issues.append(str(exc))
    return issues

def main():
    if len(sys.argv) != 3:
        print('Usage: script before.json proposed.json', file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding='utf-8') as f:
        before = json.load(f)
    with open(sys.argv[2], encoding='utf-8') as f:
        proposed = json.load(f)
    issues = check(before, proposed)
    print(json.dumps({'status': 'BLOCK' if issues else 'PASS_READONLY_PREFLIGHT',
                      'issues': issues}, ensure_ascii=False))
    return 1 if issues else 0

if __name__ == '__main__':
    raise SystemExit(main())