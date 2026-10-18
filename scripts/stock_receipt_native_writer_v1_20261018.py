"""Native two-table receipt writer adapter for STOCK_SETTLEMENT.

Only invoke with a genuine v11 receipt_plan from the original scheduled worker,
a backend-verified owned lease, and an injected authorized Sheets client.
Never infer Natural or provider MessageReference from a successful write.
"""
from __future__ import annotations

RECEIPT_FIELDS = ('RunID','TargetDate','TaskProfile','ReportSHA256','ReportArtifactID','ReportGeneratedAt','DeliveryAttemptedAt','DeliveryChannel','PlatformMessageEvidence','UserVisibleMessageID','DeliveryStatus','ReadbackStatus','SameSHAConfirmed','MissingFields','ConfigID','ConfigHashSHA256','FinalStatus','NaturalEligible','UpdatedAt','Notes')
OBS_FIELDS = ('TargetDate','TaskProfile','TaskID','EnabledAtSeal','NotificationsAtSeal','EmailAtSeal','Schedule','RunStatus','ReportStatus','SaveStatus','ReadbackStatus','MessageEvidenceStatus','DeliveryState','ReportSHA','ArtifactID','UserVisibleMessageID','ConfigID','GovernanceBundleSHA','LastCheckedAt','IncidentCode','TriggerEvidenceStatus','ExecutionEvidenceStatus')


def _inspect(client, spreadsheet_id, sheet, fields, row, key_columns):
    rows = client.read_rows(spreadsheet_id, sheet)
    if not rows or tuple(rows[0]) != fields:
        raise ValueError(sheet + '_HEADER_DRIFT')
    matches = [r for r in rows[1:] if len(r) == len(fields)
               and all(r[i] == row[i] for i in key_columns)]
    if len(matches) > 1:
        raise ValueError(sheet + '_DUPLICATE_KEY')
    if matches and list(matches[0]) != list(row):
        raise ValueError(sheet + '_CONTENT_CONFLICT')
    return bool(matches)


def write_native_receipts(*, plan, actions, client, spreadsheet_id,
                          lease_token, lease_verified):
    """Native append+readback, resumable if one table was already appended.

    client.read_rows(spreadsheet_id, tab) returns header+all values;
    client.append_row(spreadsheet_id, tab, values) does one native append.
    A live-owned lease is required from the caller; this helper cannot acquire it.
    """
    if not lease_verified or not lease_token:
        raise PermissionError('OWNED_LIVE_LEASE_REQUIRED')
    if not actions.get('AutoWriteAllowed'):
        raise ValueError('PLAN_NOT_WRITEABLE')
    a, b = plan['ReceiptRow'], plan['ObservabilityRow']
    if len(a) != 20 or len(b) != 22 or a[1] != b[0] or a[2] != b[1] or a[3] != b[13]:
        raise ValueError('CROSS_TABLE_IDENTITY_MISMATCH')
    if (plan.get('RunID') != a[0] or plan.get('TargetDate') != a[1]
            or plan.get('ReportSHA') != a[3]):
        raise ValueError('FROZEN_PLAN_IDENTITY_MISMATCH')
    if plan.get('Authority') != 'CURRENT_RUN_BYTES_ONLY_NO_AUTOMATIC_FORMAL_NATURAL':
        raise ValueError('UNVERIFIED_PLAN_AUTHORITY')
    if plan.get('NativeWriteStatus') != 'NOT_EXECUTED':
        raise ValueError('PLAN_ALREADY_EXECUTED')
    specs = [
        ('STOCK_Delivery_Receipt', RECEIPT_FIELDS, a, (0, 1, 2), 'ReceiptAction'),
        ('STOCK_Delivery_Observability', OBS_FIELDS, b, (0, 1), 'ObservabilityAction'),
    ]
    for name, fields, row, key, action in specs:
        exists = _inspect(client, spreadsheet_id, name, fields, row, key)
        expected = 'NO_OP_IDEMPOTENT' if exists else 'APPEND_REQUIRED'
        if actions.get(action) != expected and not (
                actions.get(action) == 'APPEND_REQUIRED' and exists):
            raise ValueError(name + '_STALE_ACTION')
    receipts = {}
    for name, fields, row, key, _ in specs:
        exists = _inspect(client, spreadsheet_id, name, fields, row, key)
        if not exists:
            client.append_row(spreadsheet_id, name, list(row))
        if not _inspect(client, spreadsheet_id, name, fields, row, key):
            raise RuntimeError(name + '_READBACK_MISSING')
        receipts[name] = 'NO_OP_READBACK_PASS' if exists else 'APPEND_READBACK_PASS'
    return receipts
