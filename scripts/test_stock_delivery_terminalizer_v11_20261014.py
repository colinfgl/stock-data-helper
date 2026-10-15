"""Pure offline positive/fail-closed tests for 19:00 settlement receipt planner.
These do NOT install it in a scheduled worker or award Natural/OOS.
"""
import copy, hashlib, importlib.util, json, pathlib, zipfile
root=pathlib.Path(__file__).resolve().parent
p=root/'stock_delivery_terminalizer_v11_20261014.py'
spec=importlib.util.spec_from_file_location('v11',p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
run='STK-SET-20261015-1900-TEST-SAME-RUN'
report=('2026-10-15 / '+run+'\n0.狀態總覽\n9.Governance/Delivery\n').encode()
sha=hashlib.sha256(report).hexdigest()
ctx=dict(RunID=run,TargetDate='2026-10-15',TaskProfile='STOCK_SETTLEMENT',
         TaskID='6a825a73808c81918c5c7b5d1fecaf28',
         TriggerClass='NORMAL_SCHEDULE',OriginalReportBytesFromSameRun=True,
         FrozenReportSHA=sha,ArtifactID='',GeneratedAt='2026-10-15 19:04 Asia/Taipei',
         CheckedAt='2026-10-15 19:10 Asia/Taipei',SaveReadbackStatus='FAILED',
         ConfigID='',ConfigHash='',ConfigStatus='NO_VALID_PRESEALED_CONFIG',
         GovernanceBundleSHA='f80bd84f865ebcaf006db8d83311d6097a38d6d4d5fe759cf797cb65e1d497df',
         FinalStatus='PARTIAL_REPORT_SAVE_FAILED',FormalEligible=False,NaturalEligible=False,
         MissingFields='BROKER_CASH7;ORIGINAL_BASIS_MISSING',EnabledAtSeal=True,
         NotificationsAtSeal=True,EmailAtSeal=True,Schedule='weekdays 19:00 Asia/Taipei',
         RunStatus='TERMINAL_RESEARCH_ONLY',ReportStatus='ORIGINAL_0_TO_9_FROZEN',
         IncidentCode='REPORT_SAVE_FAILED',ExecutionEvidenceStatus='SOURCE_BYTES_SHA_CHECKED')
case={}
def check(n,fun,expect_reject=False):
    try:
        result=fun()
        case[n]=(bool(result) and not expect_reject)
    except (ValueError,KeyError,TypeError):
        case[n]=expect_reject

def plan(c=None,raw=report,rh=None,oh=None):
    return m.receipt_plan(ctx if c is None else c,raw,
        list(m.RECEIPT_FIELDS) if rh is None else rh,
        list(m.OBS_FIELDS) if oh is None else oh)

def mutate(**kwargs):return {**ctx,**kwargs}

v=plan()
check('no_config_and_failed_save_can_accurately_emit_rows',lambda:len(v['ReceiptRow'])==20 and len(v['ObservabilityRow'])==22)
check('no_artifact_id_is_not_fabricated',lambda:v['ReceiptRow'][4]=='' and v['ObservabilityRow'][14]=='')
check('no_config_hash_stays_blank',lambda:v['ReceiptRow'][14]==v['ReceiptRow'][15]=='' and v['ObservabilityRow'][16]=='')
check('save_failure_is_explicit',lambda:v['ObservabilityRow'][9]=='FAIL' and v['ObservabilityRow'][10]=='NOT_VERIFIED_ARTIFACT')
check('source_bytes_not_crossartifact_verified',lambda:v['ReceiptRow'][11]=='REPORT_BYTES_ONLY_NO_ARTIFACT_READBACK')
check('explicit_missing_is_merged',lambda:all(z in v['ReceiptRow'][13] for z in ('BROKER_CASH7','NO_VALID_PRESEALED_CONFIG','ORIGINAL_REPORT_ARTIFACT_MISSING')))
check('no_fake_natural_or_oos_credit',lambda:v['ReceiptRow'][17]=='NO' and v['NaturalCredit']==v['OOSCredit']==0)
check('no_platform_msg',lambda:v['ReceiptRow'][10]=='UNVERIFIED_NONBLOCKING' and v['ReceiptRow'][9]=='')
check('reported_as_nonnative_plan',lambda:v['NativeWriteStatus']==v['ReadbackStatus']=='NOT_EXECUTED')
check('append_candidates_both',lambda:m.plan_actions(v,[],[])['AutoWriteAllowed'])
check('exact_repeat_idempotent',lambda:m.plan_actions(v,[v['ReceiptRow']],[v['ObservabilityRow']])['ReceiptAction']=='NO_OP_IDEMPOTENT')
check('sha_conflict_existing_block',lambda:m.plan_actions(v,[v['ReceiptRow'][:3]+['1'*64]+v['ReceiptRow'][4:]],[])['AutoWriteAllowed']==False)
check('duplicate_date_profile_block',lambda:m.plan_actions(v,[],[v['ObservabilityRow'],v['ObservabilityRow']])['AutoWriteAllowed']==False)
check('completed_research_without_formal_seal_and_artifact',lambda:(lambda z:z['ReceiptRow'][17]=='NO' and z['ReceiptRow'][11]=='PASS_RAW_REPORT_SHA')(plan(mutate(SaveReadbackStatus='PASS',ArtifactID='DRIVE:valid-real-source',FinalStatus='RESEARCH_SETTLEMENT_COMPLETE_FORMAL_BLOCKED'))))
check('real_config_formal_research_with_save',lambda:(lambda z:z['ConfigEvidenceStatus']=='VALID' and z['ReceiptRow'][17]=='NO')(plan(mutate(ConfigID='STOCK-CFG-TEST',ConfigHash='a'*64,ConfigStatus='PRESEALED',SaveReadbackStatus='PASS',ArtifactID='DRIVE:valid-original',FinalStatus='RESEARCH_SETTLEMENT_COMPLETE_FORMAL_BLOCKED'))))
check('valid_full_with_explicit_formal_true_does_not_auto_credit',lambda:(lambda z:z['NaturalCredit']==0 and z['OOSCredit']==0 and z['ReceiptRow'][17]=='YES')(plan(mutate(ConfigID='STOCK-CFG-TEST',ConfigHash='a'*64,ConfigStatus='PRESEALED',SaveReadbackStatus='PASS',ArtifactID='DRIVE:valid-original',FinalStatus='RESEARCH_SETTLEMENT_COMPLETE',FormalEligible=True,NaturalEligible=True,NaturalEvidenceVerified=True,MorningNaturalReceiptRunID='TRUE-MORNING-RUN-TEST',SameRunTerminalProofID='TRUE-SAME-RUN-TEST'))))
# Negative guards: missing bytes, fake scheduled origin, fake SHA, spoofed platform evidence, etc.
negative={
  'manual_origin_cannot_poison_observability':lambda:plan(mutate(TriggerClass='MANUAL_RESEARCH_RECOVERY')),
  'unverified_original_worker_cannot_claim':lambda:plan(mutate(OriginalReportBytesFromSameRun=False)),
  'missing_original_bytes':lambda:plan(ctx,b''),
  'tampered_report_sha':lambda:plan(ctx,report+b'EDIT'),
  'wrong_report_runid':lambda:plan(ctx,b'2026-10-15 no same run id'),
  'wrong_report_day':lambda:plan(ctx,b'2026-10-13 '+run.encode()),
  'receipt_header_drift':lambda:plan(ctx,report,['broken_header']),
  'observability_header_drift':lambda:plan(ctx,report,None,['broken_header']),
  'invalid_task_profile':lambda:plan(mutate(TaskProfile='STOCK_OTHER')),
  'missing_no_config_qualification':lambda:plan(mutate(FormalEligible=None)),
  'missing_no_config_explicit_gate':lambda:plan(mutate(ConfigStatus='UNKNOWN')),
  'partial_config_no_sha':lambda:plan(mutate(ConfigID='CFG-WITHOUT-HASH')),
  'fake_sha_without_configid':lambda:plan(mutate(ConfigHash='a'*64)),
  'natural_false_formal_missing_conflict':lambda:plan(mutate(NaturalEligible=True)),
  'natural_without_independent_proof':lambda:plan(mutate(ConfigID='STOCK-CFG-TEST',ConfigHash='a'*64,SaveReadbackStatus='PASS',ArtifactID='DRIVE:actual',FormalEligible=True,NaturalEligible=True)),
  'natural_true_requires_formal':lambda:plan(mutate(ConfigID='STOCK-CFG-TEST',ConfigHash='a'*64,FormalEligible=False,NaturalEligible=True)),
  'save_unverified_status':lambda:plan(mutate(SaveReadbackStatus='UNKNOWN')),
  'save_pass_no_artifact':lambda:plan(mutate(SaveReadbackStatus='PASS')),
  'missing_bundle_sha':lambda:plan(mutate(GovernanceBundleSHA='')),
  'false_report_saved_and_natural':lambda:plan(mutate(ConfigID='STOCK-CFG-TEST',ConfigHash='a'*64,FormalEligible=True,NaturalEligible=True)),
  'save_failed_with_pass_final':lambda:plan(mutate(FinalStatus='PASS_COMPLETE')),
  'false_platform_evidence':lambda:plan(mutate(PlatformMessageEvidence={'Verified':True,'RunID':run,'ReportSHA':sha})),
  'wrong_sha_platform_evidence':lambda:plan(mutate(PlatformMessageEvidence={'Verified':True,'RunID':run,'ReportSHA':'a'*64,'UserVisibleMessageID':'msg','DeliveryTimestamp':'2026-10-15 19:20 Asia/Taipei'})),
  'missing_final_status':lambda:plan(mutate(FinalStatus='')),
}
for k,vv in negative.items():check(k,vv,True)
# Confirm old approved original v10 rejects missing config even with save PASS;
# this is a REAL code-path comparison, not an invented inference.
oldpath=root/'stock_delivery_terminalizer_v10_reference_20261012.py'
old=oldpath.read_bytes()
assert hashlib.sha256(old).hexdigest()=='0e48af9ac07308dec3d857396fa0e946300786fc74e20fae707e1431af171154'
import tempfile
with tempfile.TemporaryDirectory() as t:
    oldpath=pathlib.Path(t)/'v10.py';oldpath.write_bytes(old)
    ospec=importlib.util.spec_from_file_location('v10',oldpath)
    o=importlib.util.module_from_spec(ospec);ospec.loader.exec_module(o)
    oldctx=mutate(SaveReadbackStatus='PASS',ArtifactID='DRIVE:verified-original')
    check('legacy_v10_demonstrable_missing_hash_rejects',lambda:o.receipt_plan(oldctx,report,list(o.RECEIPT_FIELDS),list(o.OBS_FIELDS)),True)

status='PASS' if all(case.values()) else 'FAIL'
obj={'status':status,'passed':sum(case.values()),'total':len(case),'cases':case,
     'scope':'SYNTHETIC_CODE_TEST_ONLY_NOT_REAL_TASK_WORKER_ORIGINAL_NOT_INSTALLED',
     'plan_example':{'receipt20':v['ReceiptRow'],'observability22':v['ObservabilityRow']},
     'natural_credit':0,'oos_credit':0}
(root/'stock_terminalizer_v11_test_result_20261014.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:obj[k] for k in ('status','passed','total','scope')},ensure_ascii=False))
if status!='PASS':
 print('FAILED', [x for x,y in case.items() if not y]);raise SystemExit(2)
