#!/usr/bin/env python3
"""V11 two-table terminal receipt builder: formal Config absence and failed SAVE become truthful partial evidence.

Offline planning only. It emits scoped native-write row proposals; it never sends
messages, claims platform delivery, or writes Google Sheets or official outcomes.
The caller must obtain unique live headers, legitimate report bytes, write exact
rows under writer lease and independently read back the live rows.
"""
from __future__ import annotations
import datetime as dt,hashlib,json,re
from typing import Any

RECEIPT_FIELDS=('RunID','TargetDate','TaskProfile','ReportSHA256','ReportArtifactID','ReportGeneratedAt',
'DeliveryAttemptedAt','DeliveryChannel','PlatformMessageEvidence','UserVisibleMessageID',
'DeliveryStatus','ReadbackStatus','SameSHAConfirmed','MissingFields','ConfigID',
'ConfigHashSHA256','FinalStatus','NaturalEligible','UpdatedAt','Notes')
OBS_FIELDS=('TargetDate','TaskProfile','TaskID','EnabledAtSeal','NotificationsAtSeal','EmailAtSeal',
'Schedule','RunStatus','ReportStatus','SaveStatus','ReadbackStatus','MessageEvidenceStatus',
'DeliveryState','ReportSHA','ArtifactID','UserVisibleMessageID','ConfigID',
'GovernanceBundleSHA','LastCheckedAt','IncidentCode','TriggerEvidenceStatus','ExecutionEvidenceStatus')

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def truth(x:Any)->str:return 'TRUE' if x is True else 'FALSE' if x is False else 'UNKNOWN'
def valid_date(s:str)->bool:
    try:dt.date.fromisoformat(s);return True
    except Exception:return False

def receipt_plan(context:dict[str,Any],original_report_bytes:bytes,receipt_headers:list[str],obs_headers:list[str])->dict:
    """Plan honest 20+22 receipts for a LIVE same-run worker, including failures.

    Research without a PRESEALED Config does not gain Formal/Natural credit.
    Failed artifact save does not erase an otherwise authentic original report.
    This plans native writes ONLY. The caller must acquire a unique owned lease,
    write, reread and verify actual physical rows; code alone never deploys.
    """
    if tuple(receipt_headers)!=RECEIPT_FIELDS:raise ValueError('DELIVERY_RECEIPT_SCHEMA_DRIFT')
    if tuple(obs_headers)!=OBS_FIELDS:raise ValueError('DELIVERY_OBSERVABILITY_SCHEMA_DRIFT')
    run=str(context['RunID']);date=str(context['TargetDate']);p=str(context['TaskProfile'])
    if not valid_date(date) or p not in ('STOCK_PREMARKET','STOCK_SETTLEMENT') or not run:
        raise ValueError('TASK_RUN_IDENTITY_INVALID')
    # In particular, a manual reconstruction CANNOT write itself to the
    # production same-run settlement receipt (which has date/profile unique).
    if context.get('TriggerClass')!='NORMAL_SCHEDULE':
        raise ValueError('NO_SAME_RUN_ORIGINAL_TRIGGER_CONTEXT')
    if context.get('OriginalReportBytesFromSameRun') is not True:
        raise ValueError('NO_SAME_RUN_ORIGINAL_REPORT_BYTES')
    if not isinstance(original_report_bytes,bytes) or not original_report_bytes:
        raise ValueError('ORIGINAL_REPORT_RAW_BYTES_MISSING')
    digest=sha(original_report_bytes)
    if context.get('FrozenReportSHA')!=digest:raise ValueError('FROZEN_REPORT_SHA_MISMATCH')
    decoded=original_report_bytes.decode('utf8')
    if run not in decoded or date not in decoded:raise ValueError('REPORT_BODY_RUN_DATE_MISMATCH')
    for field in ('GeneratedAt','CheckedAt'):
        if not isinstance(context.get(field),str) or not context[field]:raise ValueError('TIMESTAMP_MISSING_'+field)
    status=str(context.get('SaveReadbackStatus',''))
    if status not in ('PASS','FAILED','UNAVAILABLE','PARTIAL'):
        raise ValueError('SAVE_READBACK_STATUS_EXPLICIT_REQUIRED')
    saved=status=='PASS'
    artifact=str(context.get('ArtifactID') or '')
    if saved and not artifact:raise ValueError('SAVE_PASS_WITHOUT_ARTIFACT')
    if not saved and context.get('NaturalEligible') is True:
        raise ValueError('UNSAVED_CANNOT_BE_NATURAL')
    if context.get('NaturalEligible') is True and context.get('FormalEligible') is not True:
        raise ValueError('NATURAL_WITHOUT_FORMAL_FORBIDDEN')
    if context.get('NaturalEligible') is True and (context.get('NaturalEvidenceVerified') is not True
         or not context.get('MorningNaturalReceiptRunID') or not context.get('SameRunTerminalProofID')):
        raise ValueError('NATURAL_REQUIRES_INDEPENDENT_MORNING_AND_SAME_RUN_PROOF')
    final=str(context.get('FinalStatus') or '')
    if not final:raise ValueError('TERMINAL_FINAL_STATUS_MISSING')
    if not saved and not any(x in final.upper() for x in ('PARTIAL','HOLD','BLOCK','FAIL','UNSAVED','UNAVAILABLE')):
        raise ValueError('UNSAVED_RESULT_MUST_HAVE_TRUTHFUL_TERMINAL_STATUS')

    # No fake zero SHA; literal EMPTY means actual Config absent.
    cfg_id=str(context.get('ConfigID') or '')
    cfg_hash=str(context.get('ConfigHash') or '')
    config_valid=bool(cfg_id and re.fullmatch('[0-9a-f]{64}',cfg_hash))
    if not config_valid:
        if cfg_id or cfg_hash:raise ValueError('CONFIG_ID_SHA_PARTIAL_INCONSISTENCY')
        if context.get('FormalEligible') is not False or context.get('NaturalEligible') is not False:
            raise ValueError('MISSING_CONFIG_REQUIRES_EXPLICIT_FORMAL_NATURAL_FALSE')
        if context.get('ConfigStatus')!='NO_VALID_PRESEALED_CONFIG':
            raise ValueError('MISSING_CONFIG_NOT_EXPLICITLY_CLASSIFIED')
    if not re.fullmatch('[0-9a-f]{64}',str(context.get('GovernanceBundleSHA',''))):
        raise ValueError('BUNDLE_SHA_MISSING')
    platform=context.get('PlatformMessageEvidence')
    ev=bool(platform and isinstance(platform,dict) and platform.get('Verified') is True
             and platform.get('ReportSHA')==digest and platform.get('RunID')==run
             and platform.get('UserVisibleMessageID') and platform.get('DeliveryTimestamp'))
    if platform and not ev:raise ValueError('PLATFORM_EVIDENCE_UNVERIFIED_DO_NOT_PROMOTE')
    delivery='DELIVERED_VERIFIED' if ev else 'UNVERIFIED_NONBLOCKING'
    msg=platform['UserVisibleMessageID'] if ev else ''
    missing=set(filter(None,str(context.get('MissingFields','')).split(';')))
    if not config_valid:missing.add('NO_VALID_PRESEALED_CONFIG')
    if not saved:missing.add('REPORT_SAVE_READBACK_'+status)
    if not artifact:missing.add('ORIGINAL_REPORT_ARTIFACT_MISSING')
    if not saved:
        actual_readback='REPORT_BYTES_ONLY_NO_ARTIFACT_READBACK'
        same_sha='PASS_ORIGINAL_REPORT_IN_MEMORY_ONLY_NO_ARTIFACT_PROOF'
        save_state='FAIL' if status=='FAILED' else 'PARTIAL' if status=='PARTIAL' else 'NOT_EXECUTED'
        checked_state='NOT_VERIFIED_ARTIFACT'
    else:
        actual_readback='PASS_RAW_REPORT_SHA'
        same_sha='PASS_SAME_ORIGINAL_REPORT_BYTES'
        save_state='PASS'
        checked_state='PASS'
    note='Original live same-run report bytes SHA verified. '
    note+=('Artifact SAVE and exact raw readback PASS. ' if saved else
           'Artifact '+status+'; no SAVE/readback success claimed. ')
    if not config_valid:note+='No original PRESEALED Config; Formal/Natural/OOS held. '
    note+='Platform message unverified.' if not ev else 'Platform evidence matched same RunID and report SHA.'
    tr=[run,date,p,digest,artifact,context['GeneratedAt'],
        platform['DeliveryTimestamp'] if ev else 'UNKNOWN_NOT_EXPOSED',
        'CHATGPT_SCHEDULED_TASK',
        'VERIFIED_PLATFORM_MESSAGE' if ev else 'UNKNOWN_NOT_EXPOSED',
        msg,delivery,actual_readback,same_sha,';'.join(sorted(missing)),
        cfg_id,cfg_hash,final,'YES' if context.get('NaturalEligible') is True and saved and config_valid else 'NO',
        context['CheckedAt'],note]
    obs=[date,p,str(context['TaskID']),truth(context.get('EnabledAtSeal')),
         truth(context.get('NotificationsAtSeal')),truth(context.get('EmailAtSeal')),
         str(context['Schedule']),str(context.get('RunStatus','UNKNOWN')),
         str(context.get('ReportStatus','GENERATED')),save_state,checked_state,
         'VERIFIED_PLATFORM_MESSAGE' if ev else 'UNKNOWN_NOT_EXPOSED',
         delivery,digest,artifact,msg,cfg_id,context['GovernanceBundleSHA'],
         context['CheckedAt'],str(context.get('IncidentCode','')),
         str(context.get('TriggerEvidenceStatus','NOT_EXPOSED')),
         str(context.get('ExecutionEvidenceStatus','REPORT_BYTES_PRESENT_NO_WRITE_PROOF'))]
    if len(tr)!=20 or len(obs)!=22:raise ValueError('RECEIPT_FIELD_COUNT_INVALID')
    return {'RunID':run,'TargetDate':date,'ReportSHA':digest,
            'ReceiptFields':list(RECEIPT_FIELDS),'ReceiptRow':tr,
            'ObservabilityFields':list(OBS_FIELDS),'ObservabilityRow':obs,
            'DeliveryState':delivery,'ConfigEvidenceStatus':'VALID' if config_valid else 'NO_VALID_PRESEALED_CONFIG',
            'ArtifactEvidenceStatus':'PASS' if saved else 'HOLD_'+status,
            'Authority':'CURRENT_RUN_BYTES_ONLY_NO_AUTOMATIC_FORMAL_NATURAL',
            'NativeWriteStatus':'NOT_EXECUTED','ReadbackStatus':'NOT_EXECUTED',
            'NaturalCredit':0,'OOSCredit':0}

def row_decision(existing_rows:list[list],candidate_row:list,headers:list[str],unique_cols:list[str])->str:
    idcs=[headers.index(k) for k in unique_cols]
    matches=[r for r in existing_rows if len(r)==len(headers) and all(r[i]==candidate_row[i] for i in idcs)]
    if not matches:return 'APPEND_REQUIRED'
    if len(matches)>1:return 'DUPLICATE_KEY_HOLD'
    previous=matches[0]
    if previous==candidate_row:return 'NO_OP_IDEMPOTENT'
    # The same delivery identity with different frozen SHA must never silently overwrite.
    sha_idx=headers.index('ReportSHA256' if 'ReportSHA256' in headers else 'ReportSHA')
    if previous[sha_idx]!=candidate_row[sha_idx]:return 'REPORT_SHA_CONFLICT_HOLD'
    return 'RECEIPT_CONTENT_DRIFT_REQUIRES_AUDIT'

def plan_actions(plan:dict,existing_receipts:list[list],existing_obs:list[list])->dict:
    rd=row_decision(existing_receipts,plan['ReceiptRow'],plan['ReceiptFields'],['RunID','TargetDate','TaskProfile'])
    od=row_decision(existing_obs,plan['ObservabilityRow'],plan['ObservabilityFields'],['TargetDate','TaskProfile'])
    return {'ReceiptAction':rd,'ObservabilityAction':od,'AutoWriteAllowed':rd in ('APPEND_REQUIRED','NO_OP_IDEMPOTENT') and od in ('APPEND_REQUIRED','NO_OP_IDEMPOTENT'),
            'RequiresLiveSheetReadback':True,'ActualWrites':0,'PlatformDelivery':plan['DeliveryState']}
