#!/usr/bin/env python3
"""Two-table stock delivery terminal receipt builder with idempotent conflict guard.

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
    if tuple(receipt_headers)!=RECEIPT_FIELDS:raise ValueError('DELIVERY_RECEIPT_SCHEMA_DRIFT')
    if tuple(obs_headers)!=OBS_FIELDS:raise ValueError('DELIVERY_OBSERVABILITY_SCHEMA_DRIFT')
    run=str(context['RunID']);date=str(context['TargetDate']);p=str(context['TaskProfile']);ref=str(context['ArtifactID'])
    if not valid_date(date) or p not in ('STOCK_PREMARKET','STOCK_SETTLEMENT') or not run or not ref:
        raise ValueError('TASK_RUN_IDENTITY_INVALID')
    if not isinstance(original_report_bytes,bytes) or not original_report_bytes:raise ValueError('ORIGINAL_REPORT_RAW_BYTES_MISSING')
    digest=sha(original_report_bytes)
    if context.get('FrozenReportSHA')!=digest:raise ValueError('FROZEN_REPORT_SHA_MISMATCH')
    decoded=original_report_bytes.decode('utf8')
    if run not in decoded or date not in decoded:raise ValueError('REPORT_BODY_RUN_DATE_MISMATCH')
    if context.get('SaveReadbackStatus')!='PASS':raise ValueError('REPORT_SAVE_READBACK_NOT_PASS')
    if not re.fullmatch('[0-9a-f]{64}',str(context.get('ConfigHash',''))):raise ValueError('CONFIG_HASH_MISSING')
    if not re.fullmatch('[0-9a-f]{64}',str(context.get('GovernanceBundleSHA',''))):raise ValueError('BUNDLE_SHA_MISSING')
    for name in ('GeneratedAt','CheckedAt'):
        if not isinstance(context.get(name),str) or not context[name]:raise ValueError('TIMESTAMP_MISSING_'+name)
    platform=context.get('PlatformMessageEvidence');evidence_ok=bool(platform and isinstance(platform,dict)
             and platform.get('Verified') is True and platform.get('ReportSHA')==digest
             and platform.get('RunID')==run and platform.get('UserVisibleMessageID')
             and platform.get('DeliveryTimestamp'))
    if platform and not evidence_ok:raise ValueError('PLATFORM_EVIDENCE_UNVERIFIED_DO_NOT_PROMOTE')
    delivery='DELIVERED_VERIFIED' if evidence_ok else 'UNVERIFIED_NONBLOCKING'
    msg=platform['UserVisibleMessageID'] if evidence_ok else ''
    # Never turn task-local notification flags into global task user settings.
    config=str(context.get('ConfigID',''))
    final=str(context.get('FinalStatus',''))
    if not final:raise ValueError('TERMINAL_FINAL_STATUS_MISSING')
    missing=str(context.get('MissingFields',''))
    tr=[run,date,p,digest,ref,context['GeneratedAt'],
        platform['DeliveryTimestamp'] if evidence_ok else 'UNKNOWN_NOT_EXPOSED',
        'CHATGPT_SCHEDULED_TASK',
        'VERIFIED_PLATFORM_MESSAGE' if evidence_ok else 'UNKNOWN_NOT_EXPOSED',
        msg,delivery,'PASS_RAW_REPORT_SHA','PASS_SAME_ORIGINAL_REPORT_BYTES',
        missing,config,context['ConfigHash'],final,
        'YES' if context.get('NaturalEligible') is True else 'NO',context['CheckedAt'],
        'Same RunID+ReportSHA+original report bytes; report saved and exact readback. '
        'Platform delivery proof not inferred from Task last_run.' if not evidence_ok else 'Verified message delivered matches original report SHA and run.']
    obs=[date,p,str(context['TaskID']),truth(context.get('EnabledAtSeal')),
         truth(context.get('NotificationsAtSeal')),truth(context.get('EmailAtSeal')),
         str(context['Schedule']),str(context.get('RunStatus','UNKNOWN')),str(context.get('ReportStatus','GENERATED')),
         'PASS','PASS',
         'VERIFIED_PLATFORM_MESSAGE' if evidence_ok else 'UNKNOWN_NOT_EXPOSED',
         delivery,digest,ref,msg,config,context['GovernanceBundleSHA'],context['CheckedAt'],
         str(context.get('IncidentCode','')),str(context.get('TriggerEvidenceStatus','NOT_EXPOSED')),
         str(context.get('ExecutionEvidenceStatus','REPORT_BYTES_READBACK_PASS'))]
    if len(tr)!=20 or len(obs)!=22:raise ValueError('RECEIPT_FIELD_COUNT_INVALID')
    return {'RunID':run,'TargetDate':date,'ReportSHA':digest,'ReceiptFields':list(RECEIPT_FIELDS),'ReceiptRow':tr,
            'ObservabilityFields':list(OBS_FIELDS),'ObservabilityRow':obs,'DeliveryState':delivery,
            'TriggerEvidence':context.get('TriggerEvidenceStatus','NOT_EXPOSED'),
            'Authority':'EVIDENCE_ONLY_NO_FORMAL_NO_NATURAL','NativeWriteStatus':'NOT_EXECUTED',
            'ReadbackStatus':'NOT_EXECUTED'}

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
